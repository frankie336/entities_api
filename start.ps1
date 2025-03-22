# Check the operating system and set the shared path
if ($env:OS -eq "Windows_NT") {
    $env:SHARED_PATH = "C:/ProgramData/entities/samba_share"
    if (-not (Test-Path $env:SHARED_PATH)) {
        # Create the shared directory for Samba
        New-Item -ItemType Directory -Force -Path $env:SHARED_PATH
    }
    # Grant Full Control to Everyone for permissions issues
    icacls $env:SHARED_PATH /grant Everyone:(F)
} elseif ($env:OSTYPE -like "*linux*") {
    $env:SHARED_PATH = "/srv/entities/samba_share"
    if (-not (Test-Path $env:SHARED_PATH)) {
        mkdir -p $env:SHARED_PATH
    }
} elseif ($env:OSTYPE -like "*darwin*") {
    $env:SHARED_PATH = "/Users/Shared/entities/samba_share"
    if (-not (Test-Path $env:SHARED_PATH)) {
        mkdir -p $env:SHARED_PATH
    }
} else {
    Write-Host "Unsupported OS detected. Exiting..."
    exit 1
}

# Output the shared path for debugging
Write-Host "Using shared path: $env:SHARED_PATH"

# Run Docker Compose
docker-compose up --build
