def test_get_namespace_0127_output_name(cli, kubectl_bin):
    seed = kubectl_bin(["create", "namespace", "gfna-0127"])
    assert seed.returncode == 0, seed.stderr
    result = cli("get", "namespace", "gfna-0127", "-o", "name")
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() != ""
