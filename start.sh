#!/bin/bash

if ($env:OS -eq "Windows_NT") {
    $env:SHARED_PATH = "C:/ProgramData/entities/samba_share"
    if (-not (Test-Path $env:SHARED_PATH)) {
        New-Item -ItemType Directory -Force -Path $env:SHARED_PATH
    }
} elseif ($env:OSTYPE -like "*linux*") {
    $env:SHARED_PATH = "/srv/entities/samba_share"
    mkdir -p $env:SHARED_PATH
} elseif ($env:OSTYPE -like "*darwin*") {
    $env:SHARED_PATH = "/Users/Shared/entities/samba_share"
    mkdir -p $env:SHARED_PATH
} else {
    Write-Host "Unsupported OS detected. Exiting..."
    exit 1
}

# Run Docker Compose
docker-compose up

