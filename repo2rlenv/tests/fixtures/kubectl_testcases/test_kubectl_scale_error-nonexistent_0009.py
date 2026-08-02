def test_scale_statefulset_0009_nonexistent(cli):
    result = cli("scale", "statefulset", "s404-sta-0009", "--replicas=1", "-n", "default")
    assert result.returncode != 0
    err = result.stderr.lower()
    assert (
        "not found" in err
        or "notfound" in err
        or "no objects passed to scale" in err
    )
