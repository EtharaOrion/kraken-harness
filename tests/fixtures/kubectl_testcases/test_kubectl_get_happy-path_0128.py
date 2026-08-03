def test_get_namespace_0128_output_jsonpa(cli, kubectl_bin):
    seed = kubectl_bin(["create", "namespace", "gfna-0128"])
    assert seed.returncode == 0, seed.stderr
    result = cli("get", "namespace", "gfna-0128", "-o", "jsonpath={.metadata.name}")
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() != ""
