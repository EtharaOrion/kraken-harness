def test_patch_unknown_flag_errors(cli, k8s_client):
    result = cli("patch", "pod", "some-pod", "--invalid-flag")
    assert result.returncode == 1
    err = result.stderr.lower()
    assert "unknown" in err or "invalid" in err
