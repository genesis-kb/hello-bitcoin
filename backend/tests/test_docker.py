import pytest
import docker
import base64

@pytest.fixture(scope="module")
def docker_client():
    return docker.from_env()

@pytest.fixture(scope="module")
def container(docker_client):
    c = docker_client.containers.run(
        "bitcoin-oj-runner",
        "sleep infinity",
        detach=True
    )
    yield c
    c.stop(timeout=2)
    c.remove(force=True)

def test_image_exists(docker_client):
    docker_client.images.get("bitcoin-oj-runner")

def test_container_starts(container):
    container.reload()
    assert container.status == "running"

def test_exec_echo(container):
    exit_code, output = container.exec_run("echo hello")
    assert exit_code == 0
    assert output.strip() == b"hello"

def test_base64_roundtrip(container):
    req = b'{"hello": "world"}'
    b64 = base64.b64encode(req).decode()
    cmd = f"sh -c 'echo {b64} | base64 -d > /tmp/req.json && cat /tmp/req.json'"
    exit_code, output = container.exec_run(cmd)
    assert exit_code == 0
    assert output.strip() == req

def test_python_available(container):
    exit_code, output = container.exec_run("python3 --version")
    assert exit_code == 0
    assert b"Python" in output

def test_node_available(container):
    exit_code, output = container.exec_run("node --version")
    assert exit_code == 0
    assert b"v" in output

def test_rust_available(container):
    exit_code, output = container.exec_run("rustc --version")
    assert exit_code == 0
