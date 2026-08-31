# every worker opens its own master and slave pool, so this number feeds straight into the
# connection budget in config.py - workers * 2 * (db_pool_size + db_max_overflow) has to stay
# under the max_connections of the database server
workers = 8
worker_class = "uvicorn.workers.UvicornWorker"
bind = "0.0.0.0:8000"
accesslog = "-"
proxy_allow_ips = "*"
