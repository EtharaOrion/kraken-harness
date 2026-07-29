from kubernetes import client


def test_label_deployment_adds_label(cli, k8s_client, kubectl_bin, tmp_path):
    ns = f"lbl-hp03-{tmp_path.name.replace('_', '-').lower()[:30]}"
    dep_name = f"dep-lbl-hp03-{tmp_path.name.replace('_', '-').lower()[:20]}"
    seed_ns = kubectl_bin(["create", "namespace", ns])
    assert seed_ns.returncode == 0, seed_ns.stderr
    apps = client.AppsV1Api(k8s_client.api_client)
    body = client.V1Deployment(
        metadata=client.V1ObjectMeta(name=dep_name, namespace=ns),
        spec=client.V1DeploymentSpec(
            replicas=1,
            selector=client.V1LabelSelector(match_labels={"app": dep_name}),
            template=client.V1PodTemplateSpec(
                metadata=client.V1ObjectMeta(labels={"app": dep_name}),
                spec=client.V1PodSpec(containers=[client.V1Container(name="c", image="nginx")]),
            ),
        ),
    )
    apps.create_namespaced_deployment(namespace=ns, body=body)
    result = cli("label", "deployment", dep_name, "-n", ns, "team=platform")
    assert result.returncode == 0, result.stderr
    assert "labeled" in result.stdout.lower()
    dep = apps.read_namespaced_deployment(name=dep_name, namespace=ns)
    assert dep.metadata.labels is not None
    assert dep.metadata.labels.get("team") == "platform"
