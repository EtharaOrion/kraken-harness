def test_label_job_0012_nonexistent(cli):
    result = cli("label", "job", "l404-job-0012", "k=v", "-n", "default")
    assert result.returncode == 1
    err = result.stderr.lower()
    assert "not found" in err or "notfound" in err
