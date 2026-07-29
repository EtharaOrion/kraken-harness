def test_get_pods_0018_invalid_flag(cli):
    result = cli("get", "pods", '--kubeconfig=/no/such/config')
    assert result.returncode != 0
    err = result.stderr.lower()
    assert "unknown" in err or "invalid" in err or "error" in err or "required" in err
