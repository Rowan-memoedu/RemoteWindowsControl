"""Decode JSON and standard SSE MCP replies, including keepalive comments."""
import json
import time

def read_response(response, request_id=1, timeout=150, progress=None):
    content_type=response.headers.get('Content-Type','')
    if 'text/event-stream' not in content_type:
        return decode_response(response.read().decode(),content_type,request_id)
    deadline=time.monotonic()+timeout
    frame=[]
    while time.monotonic()<deadline:
        line=response.readline().decode().rstrip('\r\n')
        if line.startswith(':'):
            if progress: progress()
            continue
        if line:
            frame.append(line)
            continue
        data='\n'.join(part[5:].lstrip(' ') for part in frame if part.startswith('data:'))
        frame=[]
        if not data:
            if response.closed: break
            continue
        message=json.loads(data)
        if message.get('id')==request_id and ('result' in message or 'error' in message):
            return message
    raise TimeoutError('MCP response deadline exceeded before a result arrived')

def decode_response(raw: str, content_type: str = '', request_id=1):
    if 'text/event-stream' not in content_type and raw.lstrip().startswith('{'):
        return json.loads(raw)
    for frame in raw.replace('\r\n','\n').split('\n\n'):
        data='\n'.join(line[5:].lstrip(' ') for line in frame.splitlines() if line.startswith('data:'))
        if not data:
            continue
        message=json.loads(data)
        if message.get('id')==request_id and ('result' in message or 'error' in message):
            return message
    raise ValueError('MCP response did not contain the expected JSON-RPC result')
