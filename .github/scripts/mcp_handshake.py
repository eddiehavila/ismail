"""Start an MCP server over stdio, list its tools and call `guide`: python mcp_handshake.py <min_tools> <cmd> [args...]"""
import json
import subprocess
import sys
import time

min_tools, cmd = int(sys.argv[1]), sys.argv[2:]
p = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, encoding='utf8')


def send(msg):
    p.stdin.write(json.dumps(msg) + '\n')
    p.stdin.flush()


def recv():
    while True:
        line = p.stdout.readline()
        if not line:
            sys.exit('server closed its stdout')
        if line.lstrip().startswith('{'):
            return json.loads(line)


t = time.time()
send({'jsonrpc': '2.0', 'id': 1, 'method': 'initialize', 'params': {
    'protocolVersion': '2025-06-18', 'capabilities': {}, 'clientInfo': {'name': 'ci', 'version': '0'}}})
print('initialize', recv()['result']['serverInfo'], f'{time.time() - t:.1f}s')
send({'jsonrpc': '2.0', 'method': 'notifications/initialized'})
send({'jsonrpc': '2.0', 'id': 2, 'method': 'tools/list'})
tools = recv()['result']['tools']
print(len(tools), 'tools')
send({'jsonrpc': '2.0', 'id': 3, 'method': 'tools/call', 'params': {'name': 'guide', 'arguments': {'project': '.'}}})
guide = recv()['result']
p.kill()
assert len(tools) >= min_tools, f'expected at least {min_tools} tools'
assert not guide.get('isError') and 'ismail' in guide['content'][0]['text'], guide
print('ok')
