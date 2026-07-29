def test_apply_namespace_manifest_creates_namespace(cli, k8s_client, tmp_path):
    ns_name = f"ns-apply-hp02-{tmp_path.name.replace('_', '-').lower()[:30]}".rstrip("-")
    manifest = tmp_path / f"{ns_name}.yaml"
    manifest.write_text(
        f"apiVersion: v1\nkind: Namespace\nmetadata:\n  name: {ns_name}\n"
    )
    result = cli("apply", "-f", str(manifest))
    assert result.returncode == 0, result.stderr
    assert f"namespace/{ns_name}" in result.stdout
    assert "created" in result.stdout or "configured" in result.stdout
    namespaces = k8s_client.list_namespace().items
    assert any(n.metadata.name == ns_name for n in namespaces)
