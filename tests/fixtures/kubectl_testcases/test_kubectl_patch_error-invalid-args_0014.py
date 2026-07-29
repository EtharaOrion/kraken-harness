def test_patch_0014_invalid_flag(cli):
    result = cli("patch", "pod", "foo", '--kubeconfig=/no/such/kc', "-p", '{"metadata":{"labels":{"a":"b"}}}')
    assert result.returncode != 0
    err = result.stderr.lower()
    assert "unknown" in err or "invalid" in err or "error" in err
