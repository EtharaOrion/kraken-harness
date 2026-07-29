def test_get_namespace_0129_output_custom(cli, kubectl_bin):
    seed = kubectl_bin(["create", "namespace", "gfna-0129"])
    assert seed.returncode == 0, seed.stderr
    result = cli("get", "namespace", "gfna-0129", "-o", "custom-columns=NAME:.metadata.name")
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() != ""
