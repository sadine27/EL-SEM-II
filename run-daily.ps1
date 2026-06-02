Set-Location "D:\MAIN EL-II\EL-SEM-II"
$env:EL_ENV_FILE = ".env"
docker compose run --rm worker python -m el run *>> "D:\MAIN EL-II\EL-SEM-II\el-daily.log"
