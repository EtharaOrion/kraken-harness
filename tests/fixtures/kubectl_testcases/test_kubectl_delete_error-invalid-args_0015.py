def test_delete_0015_invalid_flag(cli):
    result = cli("delete", "pod", "foo", '--kubeconfig=/no/such/kc')
    assert result.returncode != 0
    err = result.stderr.lower()
    assert "unknown" in err or "invalid" in err or "error" in err
