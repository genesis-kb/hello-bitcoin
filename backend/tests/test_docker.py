import docker
import base64

client = docker.from_env()
container = client.containers.run("bitcoin-oj-runner", "sleep infinity", detach=True)
try:
    req = b'{"hello": "world"}'
    b64 = base64.b64encode(req).decode()
    cmd = f"sh -c 'echo {b64} | base64 -d > /tmp/req.json && cat /tmp/req.json'"
    exit_code, output = container.exec_run(cmd)
    print(f"Exit code: {exit_code}")
    print(f"Output: {output}")
finally:
    container.stop()
    container.remove()
