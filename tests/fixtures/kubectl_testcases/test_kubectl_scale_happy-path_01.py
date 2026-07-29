from kubernetes import client


def test_scale_deployment_up_to_three(cli, k8s_client, kubectl_bin):
    kubectl_bin(["create", "namespace", "scale-dep-hp01"])
    dep = client.V1Deployment(
        metadata=client.V1ObjectMeta(name="d-hp01", namespace="scale-dep-hp01"),
        spec=client.V1DeploymentSpec(
            replicas=1,
            selector=client.V1LabelSelector(match_labels={"app": "d-hp01"}),
            template=client.V1PodTemplateSpec(
                metadata=client.V1ObjectMeta(labels={"app": "d-hp01"}),
                spec=client.V1PodSpec(containers=[client.V1Container(name="c", image="nginx")]),
            ),
        ),
    )
    client.AppsV1Api(k8s_client.api_client).create_namespaced_deployment(namespace="scale-dep-hp01", body=dep)
    result = cli("scale", "deployment", "d-hp01", "--replicas=3", "-n", "scale-dep-hp01")
    assert result.returncode == 0, result.stderr
    assert "scaled" in result.stdout.lower()
    read = client.AppsV1Api(k8s_client.api_client).read_namespaced_deployment(name="d-hp01", namespace="scale-dep-hp01")
    assert read.spec.replicas == 3
