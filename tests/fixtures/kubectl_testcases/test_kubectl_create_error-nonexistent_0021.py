def test_create_configmap_0021_duplicate_fails(cli):
    r1 = cli("create", "configmap", "dup-0021", "--from-literal=k=v", "-n", "default")
    assert r1.returncode == 0, r1.stderr
    r2 = cli("create", "configmap", "dup-0021", "--from-literal=k=v", "-n", "default")
    assert r2.returncode != 0
    err = r2.stderr.lower()
    assert "already exists" in err or "alreadyexists" in err
