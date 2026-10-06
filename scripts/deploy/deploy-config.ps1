# Testbed deploy — gitignored; do not commit.

$TestbedHost = "nyraservices-testbed.net"
$TestbedUser = "ubuntu"
$SshKeyPath = "D:\Sudha\Nyra\codedetails\nyraservices.pem"

$RemoteApiDir = "/home/ubuntu/nyra-mes-api"
$RemoteUiDir = "/home/ubuntu/testbed/tenants/mes"
$RemoteApiService = "nyra-mes-api"
$RemoteApiPort = "8010"

# Optional: RDS Secrets Manager ARN/name. Leave empty to auto-discover on EC2.
$MesCoreDbSecretId = "rds!db-36663457-9b38-40d7-a4e7-bb4b65ac1f79"
