docker build -t mysolutionname:somerandomidentifier .

windows
docker run --rm -v "$(Get-Location)\input:/app/input" -v "$(Get-Location)\output:/app/output" --network none mysolutionname:somerandomidentifier

linux/macOS
docker run --rm -v "$(pwd)/input":/app/input -v "$(pwd)/output":/app/output --network none mysolutionname:somerandomidentifier