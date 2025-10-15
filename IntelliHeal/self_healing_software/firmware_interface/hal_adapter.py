# firmware_interface/hal_adapter.py
import asyncio
import json
import time
from typing import Optional

class HALAdapter:
    """
    HAL Adapter that exposes async start()/stop(), send_json(), and read_json().
    Internally runs ONE reader coroutine that places parsed JSON messages onto an asyncio.Queue.
    This prevents multiple coroutines from calling StreamReader.readline()/readuntil() concurrently.
    """

    def __init__(self, mode="tcp", tcp_host="127.0.0.1", tcp_port=9000, reconnect_interval=1.0):
        self.mode = mode
        self.tcp_host = tcp_host
        self.tcp_port = tcp_port
        self.reconnect_interval = reconnect_interval

        # connection objects
        self._reader: Optional[asyncio.StreamReader] = None
        self._writer: Optional[asyncio.StreamWriter] = None

        # one queue for incoming parsed json messages
        self._in_q: asyncio.Queue = asyncio.Queue()

        # background tasks
        self._reader_task: Optional[asyncio.Task] = None
        self._connect_task: Optional[asyncio.Task] = None

        # locks
        self._writer_lock = asyncio.Lock()

        # running flag
        self._running = False

    async def start(self):
        """
        Start the adapter. For tcp mode it will attempt to connect and spawn the reader task.
        """
        self._running = True
        if self.mode == "tcp":
            # start connect loop as a background task (establish and re-establish connection)
            self._connect_task = asyncio.create_task(self._connect_loop())
        else:
            raise NotImplementedError("Only tcp mode is implemented in this adapter.")

    async def stop(self):
        """
        Stop the adapter: cancel background tasks, close streams, flush queue.
        """
        self._running = False

        # cancel reader task first (if exists)
        if self._reader_task:
            self._reader_task.cancel()
            await asyncio.gather(self._reader_task, return_exceptions=True)
            self._reader_task = None

        # cancel connect loop
        if self._connect_task:
            self._connect_task.cancel()
            await asyncio.gather(self._connect_task, return_exceptions=True)
            self._connect_task = None

        # close current writer/reader
        try:
            if self._writer:
                self._writer.close()
                await self._writer.wait_closed()
        except Exception:
            pass

        self._writer = None
        self._reader = None

        # optionally drain/clear the queue
        while not self._in_q.empty():
            try:
                self._in_q.get_nowait()
            except Exception:
                break

    async def _connect_loop(self):
        """
        Try to connect; on success spawn _reader_task and wait until connection breaks, then reconnect.
        """
        while self._running:
            try:
                # attempt connection
                reader, writer = await asyncio.open_connection(self.tcp_host, self.tcp_port)
                self._reader = reader
                self._writer = writer
                print(f"HALAdapter: connected to tcp {self.tcp_host}:{self.tcp_port}")

                # spawn single reader task to feed queue
                if self._reader_task is None or self._reader_task.done():
                    self._reader_task = asyncio.create_task(self._reader_loop())

                # wait here until connection is closed or task ends
                # monitor the reader_task - if it ends, assume connection broken and loop to reconnect
                await self._reader_task
            except asyncio.CancelledError:
                break
            except Exception as e:
                # connection failed: wait and retry
                print(f"HALAdapter: connect error: {e}")
                await asyncio.sleep(self.reconnect_interval)
            finally:
                # cleanup streams to allow next reconnect
                try:
                    if self._writer:
                        self._writer.close()
                        await self._writer.wait_closed()
                except Exception:
                    pass
                self._writer = None
                self._reader = None

                # if still running, wait a bit before retrying
                if self._running:
                    await asyncio.sleep(self.reconnect_interval)

    async def _reader_loop(self):
        """
        Single reader coroutine that reads lines from the socket and pushes parsed JSON to the queue.
        This is the only coroutine that performs StreamReader.readline() operations.
        """
        reader = self._reader
        if reader is None:
            return

        try:
            while self._running:
                # use readline (expects newline-delimited JSON)
                try:
                    line = await reader.readline()
                except asyncio.CancelledError:
                    break
                except Exception as e:
                    # reading error -> break to cause reconnect
                    print("HALAdapter read_json error (readline):", e)
                    break

                if not line:
                    # EOF or closed connection
                    print("HALAdapter: connection closed by peer (reader returned empty)")
                    break

                try:
                    text = line.decode().strip()
                    if not text:
                        continue
                    msg = json.loads(text)
                    # put message into queue without blocking
                    try:
                        self._in_q.put_nowait(msg)
                    except asyncio.QueueFull:
                        # if full (unlikely), drop oldest then put
                        _ = await self._in_q.get()
                        self._in_q.put_nowait(msg)
                except Exception as e:
                    # couldn't parse JSON: log and continue
                    print("HALAdapter: parse error for incoming line:", e)
                    continue

        finally:
            # When reader loop exits, ensure reader/writer cleaned up by connect loop
            return

    async def send_json(self, obj: dict):
        """
        Send newline-delimited JSON to the HAL peer.
        """
        if self._writer is None:
            raise ConnectionError("HALAdapter: no writer/connection")
        text = json.dumps(obj) + "\n"
        async with self._writer_lock:
            try:
                self._writer.write(text.encode())
                await self._writer.drain()
            except Exception as e:
                print("HALAdapter send error:", e)
                raise

    async def read_json(self, timeout: Optional[float] = None):
        """
        Consume the next JSON message from the internal queue (populated by the single reader).
        Timeout (seconds) can be provided.
        Returns parsed object or None on timeout.
        """
        try:
            if timeout:
                msg = await asyncio.wait_for(self._in_q.get(), timeout=timeout)
            else:
                msg = await self._in_q.get()
            return msg
        except asyncio.TimeoutError:
            return None
        except asyncio.CancelledError:
            # propagate cancellation so shutdown flows can cancel callers
            raise
        except Exception as e:
            print("HALAdapter read_json error:", e)
            return None
