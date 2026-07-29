def test_patch_job_0012_nonexistent(cli):
    result = cli("patch", "job", "p404-job-0012", "-n", "default", "-p", '{"metadata":{"labels":{"a":"b"}}}')
    assert result.returncode != 0
    err = result.stderr.lower()
    assert "not found" in err or "notfound" in err
