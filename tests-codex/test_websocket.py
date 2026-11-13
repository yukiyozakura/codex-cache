import asyncio
import base64
import hashlib
import importlib.util
import os
from pathlib import Path
import stat
import struct
import types
import unittest
from unittest.mock import AsyncMock, patch

spec = importlib.util.spec_from_file_location('cache', Path(__file__).resolve().parents[1] / 'src/cache.py')
c = importlib.util.module_from_spec(spec)
spec.loader.exec_module(c)


class Writer:
    def __init__(self): self.data, self.closed = bytearray(), False
    def write(self, data): self.data.extend(data)
    def is_closing(self): return self.closed
    def close(self): self.closed = True
    async def drain(self): pass
    async def wait_closed(self): pass


def server_frame(opcode, payload, fin=True):
    n = len(payload)
    length = bytes([n]) if n < 126 else b'\x7e' + struct.pack('!H', n)
    return bytes([(0x80 if fin else 0) | opcode]) + length + payload


def client_payload(data):
    n, at = data[1] & 127, 2
    if n == 126: n, at = struct.unpack('!H', data[2:4])[0], 4
    elif n == 127: n, at = struct.unpack('!Q', data[2:10])[0], 10
    assert data[1] & 128
    mask, payload = data[at:at+4], data[at+4:at+4+n]
    return bytes(v ^ mask[i % 4] for i,v in enumerate(payload))


class WebSocketTests(unittest.IsolatedAsyncioTestCase):
    def client(self, data=b''):
        ws = c.UnixWebSocket()
        ws.reader, ws.writer = asyncio.StreamReader(), Writer()
        ws.reader.feed_data(data)
        ws.reader.feed_eof()
        return ws

    async def test_fragmented_utf8_and_ping_pong(self):
        text = 'hello 世界'.encode()
        ws = self.client(server_frame(1,text[:8],False)+server_frame(9,b'keepalive')+server_frame(0,text[8:]))
        self.assertEqual(await ws.receive(), 'hello 世界')
        self.assertEqual(ws.writer.data[0], 0x8a)
        self.assertEqual(client_payload(ws.writer.data), b'keepalive')

    async def test_masked_client_frames_all_length_forms(self):
        for n in [0, 100, 126, 65536]:
            ws = self.client()
            ws.send('x'*n)
            self.assertEqual(client_payload(ws.writer.data), b'x'*n)

    async def test_invalid_frames_and_oversized_messages_fail_closed(self):
        for data in [b'\xc1\x00', b'\x81\x80', server_frame(0,b'x'), b'\x09\x00', server_frame(2,b'bytes'), b'\x81\x7f'+struct.pack('!Q',c.UnixWebSocket.LIMIT+1)]:
            with self.assertRaises(ValueError): await self.client(data).receive()

    async def test_close_and_eof(self):
        ws = self.client(server_frame(8,b'\x03\xe8'))
        self.assertIsNone(await ws.receive())
        self.assertEqual(ws.writer.data[0],0x88)
        await ws.close()
        self.assertTrue(ws.writer.closed)
        self.assertIsNone(await self.client().receive())

    async def test_socket_owner_and_permissions_checked_before_connect(self):
        for mode,uid in [(stat.S_IFREG|0o600,os.getuid()),(stat.S_IFSOCK|0o666,os.getuid()),(stat.S_IFSOCK|0o600,os.getuid()+1)]:
            with patch.object(c.Path,'stat',return_value=types.SimpleNamespace(st_mode=mode,st_uid=uid)), patch('asyncio.open_unix_connection',new_callable=AsyncMock) as connect:
                with self.assertRaises(ValueError): await c.UnixWebSocket.connect('/test.sock')
                connect.assert_not_called()

    async def test_http_upgrade_verified_and_unsolicited_extensions_rejected(self):
        for bad in [False,True]:
            reader = asyncio.StreamReader()
            class HandshakeWriter(Writer):
                def write(self,data):
                    super().write(data)
                    key = data.decode().split('Sec-WebSocket-Key: ')[1].split('\r\n')[0]
                    accept = base64.b64encode(hashlib.sha1((key+'258EAFA5-E914-47DA-95CA-C5AB0DC85B11').encode()).digest()).decode()
                    extra = 'Sec-WebSocket-Extensions: permessage-deflate\r\n' if bad else ''
                    reader.feed_data(('HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: keep-alive,Upgrade\r\nSec-WebSocket-Accept: '+accept+'\r\n'+extra+'\r\n').encode())
            writer = HandshakeWriter()
            with patch.object(c.Path,'stat',return_value=types.SimpleNamespace(st_mode=stat.S_IFSOCK|0o600,st_uid=os.getuid())), patch('asyncio.open_unix_connection',new_callable=AsyncMock,return_value=(reader,writer)):
                if bad:
                    with self.assertRaises(ValueError): await c.UnixWebSocket.connect('/test.sock')
                    self.assertTrue(writer.closed)
                else:
                    ws=await c.UnixWebSocket.connect('/test.sock')
                    # No separate reader task here; close the fixture directly.
                    writer.close()

if __name__=='__main__': unittest.main()
