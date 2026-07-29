def test_patch_bad_type_errors(cli, k8s_client):
    result = cli("patch", "pod", "some-pod", "-n", "default", "--type=badtype", "-p", '{}')
    assert result.returncode == 1
    err = result.stderr.lower()
    assert "type" in err or "invalid" in err or "unknown" in err
