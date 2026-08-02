def test_get_job_0012_nonexistent(cli):
    result = cli("get", "job", "missing-job-0012", "-n", "default")
    assert result.returncode == 1
    err = result.stderr.lower()
    assert "not found" in err or "notfound" in err
