# Used by .github/workflows/deploy.yml. Input: `aws ecs describe-task-definition --query taskDefinition`.
# Output: the same definition with only the images changed, ready for `register-task-definition`.
# Arguments: --arg core <image> --arg edge <image> --arg agent <image>.
# Fails (non-zero exit) when the input is not a task definition or no container image was replaced,
# so a renamed container cannot slip through with the old image still deployed.
del(.taskDefinitionArn, .revision, .status, .requiresAttributes, .compatibilities, .registeredAt, .registeredBy)
| .containerDefinitions |= map(
    if (.name == "core" or .name == "worker" or .name == "migrate") then .image = $core
    elif .name == "edge" then .image = $edge
    elif .name == "ops-agent" then .image = $agent
    else . end)
| if any(.containerDefinitions[]; .image == $core or .image == $edge or .image == $agent)
  then .
  else error("no container image was replaced: unexpected container names") end
