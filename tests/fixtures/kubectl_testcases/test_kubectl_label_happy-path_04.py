def test_label_namespace_adds_label(cli, k8s_client, kubectl_bin, tmp_path):
    ns = f"lbl-hp04-{tmp_path.name.replace('_', '-').lower()[:30]}"
    seed = kubectl_bin(["create", "namespace", ns])
    assert seed.returncode == 0, seed.stderr
    result = cli("label", "namespace", ns, "tier=infra")
    assert result.returncode == 0, result.stderr
    assert "labeled" in result.stdout.lower()
    got = k8s_client.read_namespace(name=ns)
    assert got.metadata.labels is not None
    assert got.metadata.labels.get("tier") == "infra"
