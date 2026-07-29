def test_apply_0023_invalid_flag(cli):
    result = cli("apply", '--kubeconfig=/no/such/kc')
    assert result.returncode != 0
    err = result.stderr.lower()
    assert "unknown" in err or "invalid" in err or "error" in err or "required" in err
