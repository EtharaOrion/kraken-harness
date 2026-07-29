from kubernetes import client


def test_scale_deployment_current_replicas_precondition_fails(cli, k8s_client, kubectl_bin):
    kubectl_bin(["create", "namespace", "scale-dep-ne02"])
    dep = client.V1Deployment(
        metadata=client.V1ObjectMeta(name="d-ne02", namespace="scale-dep-ne02"),
        spec=client.V1DeploymentSpec(
            replicas=1,
            selector=client.V1LabelSelector(match_labels={"app": "d-ne02"}),
            template=client.V1PodTemplateSpec(
                metadata=client.V1ObjectMeta(labels={"app": "d-ne02"}),
                spec=client.V1PodSpec(containers=[client.V1Container(name="c", image="nginx")]),
            ),
        ),
    )
    client.AppsV1Api(k8s_client.api_client).create_namespaced_deployment(namespace="scale-dep-ne02", body=dep)
    result = cli("scale", "deployment", "d-ne02", "--current-replicas=99", "--replicas=5", "-n", "scale-dep-ne02")
    assert result.returncode == 1
    err = result.stderr.lower()
    assert "precondition" in err or "current-replicas" in err or "conflict" in err or "expected" in err
