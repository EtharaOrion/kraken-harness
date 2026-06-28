# Why `@mock_aws` is removed from generated cli_app tests

## Summary

The `cli_app` test-synthesis prompt previously instructed the model to decorate
every generated test with `@mock_aws` (from `moto`). This is incorrect for the
test architecture these tasks use and was producing broken, non-discriminative
tests. The fix removes the instruction and adds a defensive `_sanitise_mock_aws()`
strip so any stray `@mock_aws` the model still emits is dropped before the test
is written.

This change does **not** weaken or alter S3 mocking. It makes the existing,
correct mocking mechanism work.

## The test architecture (ground truth)

Generated `cli_app` tasks mock S3 with a **real moto HTTP server**, not the
in-process `@mock_aws` patcher. From a shipped task's `conftest.py`:

```python
from moto.server import ThreadedMotoServer

@pytest.fixture
def moto_server():
    server = ThreadedMotoServer(port=0)
    server.start()
    endpoint = f"http://127.0.0.1:{server._server.socket.getsockname()[1]}"
    yield endpoint
    server.stop()

@pytest.fixture
def s3_client(moto_server):
    return boto3.client("s3", endpoint_url=moto_server, ...)

@pytest.fixture
def cli(moto_server):
    def _run(*args, ...):
        env["AWS_ENDPOINT_URL_S3"] = moto_server   # real endpoint
        return subprocess.run(
            [sys.executable, "/workspace/submission/main.py", *args],
            env=env, capture_output=True, text=True,
        )
    return _run
```

Two facts follow:

1. The candidate CLI runs in a **subprocess** (`subprocess.run([...])`).
2. Both the test's `s3_client` and the subprocess reach the **same real moto
   server over HTTP** via `AWS_ENDPOINT_URL_S3`.

## Why `@mock_aws` is wrong here

`@mock_aws` works by monkey-patching `boto3`/`botocore` **inside the current
Python process**. It has two fatal problems against this architecture:

1. **It cannot reach the subprocess.** The decorator patches only the test
   process's memory. The submission runs in a separate process and never sees
   the patch.

2. **It conflicts with `ThreadedMotoServer`.** In-process patching and a real
   server are two mutually exclusive moto modes. Stacking them makes the test's
   in-process `s3_client` view diverge from the state the subprocess writes to
   the server, yielding false failures.

In practice the model often emitted `@mock_aws` **without importing it**, so
tests failed at pytest collection with `NameError`, scoring every submission
(including the reference solution) 0. The task became non-discriminative.

## Empirical confirmation

`@mock_aws` does not cross a process boundary. Creating a bucket under
`@mock_aws` in a parent process and listing buckets from a child process:

```
PARENT_CREATED: parent-mock-bucket under @mock_aws
SUBPROCESS_ERROR: ClientError (InvalidAccessKeyId) when calling ListBuckets
```

The subprocess does not see the mocked bucket; with no endpoint override it
attempts real AWS and fails on credentials. This is moto's documented behavior:
`@mock_aws` is in-process only.

After the fix, real end-to-end runs behave correctly: the `oracle` (reference
solution) scores `1.0` and the `nop` (empty submission) scores `0.0` against the
`ThreadedMotoServer`, confirming the mock serves consistent state and the task is
discriminative.

## The fix

- Prompt: replace "Use `@mock_aws` decorator" with an explicit instruction that a
  real moto server is already wired via `conftest.py` and `@mock_aws` must not be
  used.
- Code: `_sanitise_mock_aws()` strips any `@mock_aws` decorator line and any
  `moto` import the model still emits, applied to the translated test before it
  is written.

## Impact on moto

None, other than letting it work. `ThreadedMotoServer` remains the sole mocking
mechanism. Removing the conflicting in-process decorator restores consistent
shared state between the test process and the submission subprocess.
