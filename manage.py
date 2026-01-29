#!/usr/bin/env python3
"""
PrecliniTrain Management CLI
Handles setup, deployment, and maintenance operations with comprehensive features.
"""

import argparse
import os
import secrets
import shutil
import subprocess
import sys
import time
import platform
import getpass
from pathlib import Path
from datetime import datetime

# --- Constants ---
ENV_FILE = ".env"
ENV_SAMPLE = "env-sample"
REQUIRED_DIRS = ["instance", "logs", "migrations"]
BANNER_WIDTH = 60
IS_WINDOWS = os.name == 'nt'

# --- Colors ---
class Colors:
    HEADER = '\033[95m'
    OKBLUE = '\033[94m'
    OKCYAN = '\033[96m'
    OKGREEN = '\033[92m'
    WARNING = '\033[93m'
    FAIL = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'
    
    @staticmethod
    def print_msg(text, color):
        if IS_WINDOWS and not os.environ.get('WT_SESSION'):
            print(text)
        else:
            print(f"{color}{text}{Colors.ENDC}")

    @staticmethod
    def header(text): Colors.print_msg(f"\n{'='*BANNER_WIDTH}\n {text}\n{'='*BANNER_WIDTH}", Colors.HEADER)
    @staticmethod
    def success(text): Colors.print_msg(f"[+] {text}", Colors.OKGREEN)
    @staticmethod
    def info(text): Colors.print_msg(f"[*] {text}", Colors.OKBLUE)
    @staticmethod
    def error(text): Colors.print_msg(f"[!] {text}", Colors.FAIL)
    @staticmethod
    def warning(text): Colors.print_msg(f"[!] {text}", Colors.WARNING)

# --- Helpers ---
def run_command(cmd, check=True, capture_output=False, shell=True, env=None):
    """Run a shell command with proper error handling."""
    try:
        result = subprocess.run(cmd, shell=shell, check=check, capture_output=capture_output, text=True, env=env)
        if capture_output:
            return result.stdout.strip()
        return result
    except subprocess.CalledProcessError as e:
        Colors.error(f"Command failed: {cmd}")
        if e.stdout:
            print(f"Stdout: {e.stdout}")
        if e.stderr:
            print(f"Stderr: {e.stderr}")
        if check:
            sys.exit(1)

def check_docker():
    """Check if Docker is running."""
    try:
        run_command("docker info", capture_output=True)
        return True
    except:
        Colors.error("Docker is not running or not accessible. Please start Docker first.")
        return False

def ensure_dirs():
    """Create required directories."""
    for d in REQUIRED_DIRS:
        if not os.path.exists(d):
            os.makedirs(d)
            Colors.info(f"Created directory: {d}")

# --- Enhanced Utilities ---

class PortManager:
    """Advanced port management with availability checking and conflict resolution."""
    
    @staticmethod
    def check_port_available(port, host='localhost'):
        """Check if a port is available."""
        import socket
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(1)
                result = s.connect_ex((host, int(port)))
                return result != 0
        except Exception as e:
            Colors.warning(f"Error checking port {port}: {e}")
            return False
    
    @staticmethod
    def find_available_port(start_port=5000, end_port=6000):
        """Find first available port in range."""
        for port in range(start_port, end_port):
            if PortManager.check_port_available(port):
                return port
        return None
    
    @staticmethod
    def suggest_alternative_ports(port, count=3):
        """Suggest alternative ports near the requested one."""
        suggestions = []
        for offset in [1, 10, 100]:
            candidate = int(port) + offset
            if PortManager.check_port_available(candidate) and candidate < 65535:
                suggestions.append(candidate)
                if len(suggestions) >= count:
                    break
        return suggestions
    
    @staticmethod
    def get_port_owner(port):
        """Identify which process is using the port."""
        if IS_WINDOWS:
             # First find PID using the port, filtering for LISTENING
             # We use findstr to look for the port AND "LISTENING"
             # Since findstr doesn't support AND easily on one line without regex, we pipe.
             cmd = f'netstat -ano | findstr :{port} | findstr LISTENING'
             res = subprocess.run(cmd, shell=True, capture_output=True, text=True)
             if not res.stdout: return None
             
             # Extract PID (last column of the first matching line)
             try:
                 # Take the first line only to avoid confusion if multiple interfaces listen
                 first_line = res.stdout.strip().split('\n')[0]
                 parts = first_line.split()
                 pid = parts[-1]
                 if pid.isdigit():
                     return int(pid)
             except:
                 pass
        else:
            # Linux
            cmd = f"lsof -t -i:{port}"
            res = subprocess.run(cmd, shell=True, capture_output=True, text=True)
            if res.stdout.strip():
                return int(res.stdout.strip().split('\n')[0])
        return None

    @staticmethod
    def is_app_using_port(port, config=None):
        """Check if THIS app is using the port with enhanced detection."""
        owner_pid = PortManager.get_port_owner(port)
        if not owner_pid: return False
        
        # 1. Check direct PID match from files
        native_pids = []
        for pf in ["logs/app.pid", "logs/gunicorn.pid"]:
            if os.path.exists(pf):
                try: 
                    with open(pf) as f: native_pids.append(int(f.read().strip()))
                except: pass
                
        if owner_pid in native_pids:
            return True

        # 2. Enhanced Windows Check: If PID doesn't match file (maybe file deleted or stale),
        # check if the process CommandLine contains our app signature.
        if IS_WINDOWS:
            try:
                # Use wmic to get command line of the process
                cmd = f'wmic process where processid={owner_pid} get commandline'
                res = subprocess.run(cmd, shell=True, capture_output=True, text=True)
                cmd_line = res.stdout.lower()
                
                # Signatures that identify our app
                signatures = [
                    "waitress", 
                    "manage.py", 
                    "flask_app",
                    "app:create_app"
                ]
                
                if any(sig in cmd_line for sig in signatures):
                    # It's us, even if PID file is missing/wrong
                    # Optional: update PID file?
                    return True
            except:
                pass

        # 3. Check Docker (if deployed via docker)
        try:
             res = subprocess.run("docker compose ps --format json", shell=True, capture_output=True, text=True)
             if f":{port}->5000/tcp" in res.stdout or f":{port}->5000" in res.stdout:
                 return True
        except:
             pass
             
        return False
        
    @staticmethod
    def get_port_info(port):
        """Get information about what's using a port."""
        if IS_WINDOWS:
            try:
                cmd = f'netstat -ano | findstr :{port}'
                result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
                return result.stdout.strip() if result.stdout else "Port in use (details unavailable)"
            except:
                return "Unable to determine"
        else:
            try:
                cmd = f"lsof -i :{port} -sTCP:LISTEN || ss -ltnp | grep :{port}"
                result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
                return result.stdout.strip() if result.stdout else "Port in use (details unavailable)"
            except:
                return "Unable to determine"


class DatabaseManager:
    """Database connectivity testing and management."""
    
    @staticmethod
    def test_connection(db_config):
        """Test database connection. Returns (success, message)."""
        db_type = db_config.get('DB_TYPE', 'sqlite')
        
        if db_type == 'sqlite':
            db_path = db_config.get('DATABASE_URL', 'instance/app.db')
            if db_path.startswith('sqlite:///'):
                db_path = db_path.replace('sqlite:///', '')
            
            # Check if directory exists
            db_dir = os.path.dirname(db_path) if '/' in db_path else 'instance'
            if not os.path.exists(db_dir):
                return False, f"Directory '{db_dir}' does not exist"
            
            # SQLite is always "connectable" if dir exists
            return True, f"SQLite database path: {db_path}"
        
        elif db_type in ['mysql', 'mariadb']:
            try:
                import pymysql
                conn = pymysql.connect(
                    host=db_config.get('DB_HOST', 'localhost'),
                    port=int(db_config.get('DB_PORT', 3306)),
                    user=db_config.get('DB_USER'),
                    password=db_config.get('DB_PASSWORD'),
                    database=db_config.get('DB_NAME'),
                    connect_timeout=5
                )
                conn.close()
                return True, f"Successfully connected to {db_config.get('DB_HOST')}:{db_config.get('DB_PORT')}"
            except ImportError:
                return False, "pymysql not installed (run: pip install pymysql)"
            except Exception as e:
                return False, f"Connection failed: {str(e)}"
        
        return False, f"Unknown database type: {db_type}"
    
    @staticmethod
    def create_database_if_not_exists(db_config):
        """Create database if it doesn't exist (MySQL only)."""
        if db_config.get('DB_TYPE') not in ['mysql', 'mariadb']:
            return True, "SQLite - database will be created automatically"
        
        try:
            import pymysql
            # Connect without specifying database
            conn = pymysql.connect(
                host=db_config.get('DB_HOST'),
                port=int(db_config.get('DB_PORT', 3306)),
                user=db_config.get('DB_USER'),
                password=db_config.get('DB_PASSWORD'),
                connect_timeout=5
            )
            cursor = conn.cursor()
            db_name = db_config.get('DB_NAME')
            cursor.execute(f"CREATE DATABASE IF NOT EXISTS `{db_name}` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci")
            conn.commit()
            cursor.close()
            conn.close()
            return True, f"Database '{db_name}' is ready"
        except Exception as e:
            return False, f"Failed to create database: {str(e)}"


class ConfigManager:
    """Manage .env configuration file."""
    
    @staticmethod
    def load_env():
        """Load .env file into dictionary."""
        config = {}
        if os.path.exists(ENV_FILE):
            with open(ENV_FILE, 'r') as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith('#') and '=' in line:
                        key, value = line.split('=', 1)
                        config[key.strip()] = value.strip()
        return config
    
    @staticmethod
    def save_env(config, backup=True):
        """Save configuration to .env file."""
        if backup and os.path.exists(ENV_FILE):
            backup_name = f"{ENV_FILE}.backup.{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            shutil.copy(ENV_FILE, backup_name)
            Colors.info(f"Backup created: {backup_name}")
        
        with open(ENV_FILE, 'w') as f:
            for key, value in config.items():
                f.write(f"{key}={value}\n")
    
    @staticmethod
    def get_value(key):
        """Get single value from .env."""
        config = ConfigManager.load_env()
        return config.get(key)
    
    @staticmethod
    def set_value(key, value, backup=True):
        """Set single value in .env."""
        config = ConfigManager.load_env()
        old_value = config.get(key)
        config[key] = value
        ConfigManager.save_env(config, backup=backup)
        return old_value
    
    @staticmethod
    def validate_value(key, value):
        """Validate configuration value. Returns (valid, message)."""
        validators = {
            'APP_PORT': lambda v: (v.isdigit() and 1 <= int(v) <= 65535, "Port must be 1-65535"),
            'DB_PORT': lambda v: (v.isdigit() and 1 <= int(v) <= 65535, "Port must be 1-65535"),
            'FLASK_DEBUG': lambda v: (v in ['0', '1', 'True', 'False'], "Must be 0, 1, True, or False"),
            'DB_TYPE': lambda v: (v in ['sqlite', 'mysql', 'postgresql'], "Must be 'sqlite', 'mysql', or 'postgresql'"),
        }
        
        if key in validators:
            valid, msg = validators[key](str(value))
            return valid, msg
        
        # Generic validation: not empty
        return bool(value), "Value cannot be empty"


class StatusTable:
    """Pretty status table for CLI output."""
    
    def __init__(self, title=None):
        self.rows = []
        self.title = title
    
    def add_row(self, name, status, details=""):
        """Add a row to the table."""
        # Determine color based on status
        if status.lower() in ['running', 'ok', 'available', 'connected', 'success']:
            status_colored = f"{Colors.OKGREEN}✓ {status}{Colors.ENDC}"
        elif status.lower() in ['stopped', 'unavailable', 'failed', 'error']:
            status_colored = f"{Colors.FAIL}✗ {status}{Colors.ENDC}"
        elif status.lower() in ['warning', 'pending']:
            status_colored = f"{Colors.WARNING}⚠ {status}{Colors.ENDC}"
        else:
            status_colored = status
        
        self.rows.append((name, status_colored, details))
    
    def render(self):
        """Print the table."""
        if self.title:
            Colors.header(self.title)
        
        if not self.rows:
            Colors.info("No data to display")
            return
        
        # Calculate column widths
        col1_width = max(len(row[0]) for row in self.rows) + 2
        col2_width = 15  # Status column (accounting for color codes)
        col3_width = 50
        
        # Print rows
        for name, status, details in self.rows:
            name_padded = name.ljust(col1_width)
            details_truncated = (details[:col3_width-3] + '...') if len(details) > col3_width else details
            print(f"  {name_padded} {status.ljust(col2_width + 20)} {details_truncated}")
        
        print()  # Empty line after table


def print_banner(text):
    """Print a fancy banner."""
    width = max(60, len(text) + 10)
    border = "═" * width
    Colors.print_msg(f"\n╔{border}╗", Colors.HEADER)
    Colors.print_msg(f"║{text.center(width)}║", Colors.HEADER)
    Colors.print_msg(f"╚{border}╝\n", Colors.HEADER)


def confirm_action(message, default=False):
    """Ask for user confirmation."""
    suffix = "[Y/n]" if default else "[y/N]"
    response = input(f"{Colors.WARNING}{message} {suffix}: {Colors.ENDC}").strip().lower()
    
    if not response:
        return default
    return response in ['y', 'yes']


class Spinner:
    """Simple spinner for long-running operations."""
    
    def __init__(self, message="Working"):
        self.message = message
    
    def __enter__(self):
        Colors.info(f"{self.message}...")
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        pass


# --- Setup Functions ---

def setup_env_file():
    """Interactive setup wizard for .env file."""
    env_sample = Path(ENV_SAMPLE)
    env_file = Path(ENV_FILE)

    print_banner("PrecliniTrain Setup Wizard")

    if env_file.exists():
        if not confirm_action(".env file already exists. Overwrite?", default=False):
            Colors.info("Setup cancelled.")
            return

    if not env_sample.exists():
        Colors.error("env-sample file not found. Cannot proceed with setup.")
        return

    # Copy env-sample to .env
    shutil.copy(env_sample, env_file)
    Colors.info("Created .env file from env-sample template.")

    # Interactive configuration
    config = ConfigManager.load_env()

    print("\n--- Deployment Mode ---")
    print("1. Docker (Recommended for production)")
    print("2. Native (Direct deployment)")
    deployment_choice = input("Choice [1]: ").strip() or "1"
    deployment_mode = 'docker' if deployment_choice == '1' else 'native'
    config['DEPLOYMENT_MODE'] = deployment_mode

    # Port configuration with availability checking
    print("\n--- Application Port ---")
    app_port = input("Application Port [5001]: ").strip() or "5001"
    
    Colors.info(f"Checking port {app_port} availability...")
    if not PortManager.check_port_available(app_port):
        Colors.warning(f"Port {app_port} is already in use!")
        alternatives = PortManager.suggest_alternative_ports(app_port, 3)
        
        if alternatives:
            Colors.info("Suggested alternative ports:")
            for i, port in enumerate(alternatives, 1):
                print(f"  {i}. {port}")
            
            choice = input(f"Choose an alternative (1-{len(alternatives)}) or press Enter to use {app_port} anyway: ").strip()
            if choice.isdigit() and 1 <= int(choice) <= len(alternatives):
                app_port = str(alternatives[int(choice) - 1])
                Colors.success(f"Port changed to {app_port}")
    else:
        Colors.success(f"Port {app_port} is available")
    
    config['APP_PORT'] = app_port

    # Security
    print("\n--- Security Configuration ---")
    secret_key = secrets.token_hex(32)
    config['SECRET_KEY'] = secret_key
    Colors.success("Generated secure SECRET_KEY.")

    # Admin credentials
    print("\n--- Admin User ---")
    admin_email = input("Admin email [admin@example.com]: ").strip() or "admin@example.com"
    admin_password = input("Admin password (leave empty to generate): ").strip()
    if not admin_password:
        admin_password = secrets.token_hex(16)
        Colors.warning(f"Generated admin password: {admin_password}")
    
    config['ADMIN_EMAIL'] = admin_email
    config['ADMIN_PASSWORD'] = admin_password

    # Service API Keys
    service_api_key = secrets.token_hex(32)
    config['SERVICE_API_KEY'] = service_api_key
    Colors.success("Generated SERVICE_API_KEY for inter-app communication.")

    sso_secret_key = secrets.token_hex(32)
    config['SSO_SECRET_KEY'] = sso_secret_key
    Colors.success("Generated SSO_SECRET_KEY for seamless login.")

    # Database configuration
    print("\n--- Database Configuration ---")
    if deployment_mode == 'docker':
        print("1. Docker Container (MariaDB)")
        print("2. External Database")
        db_choice = input("Choice [1]: ").strip() or "1"
        
        if db_choice == '1':
            # Docker internal database
            config['DB_TYPE'] = 'mysql'
            config['DB_HOST'] = 'db'
            config['DB_PORT'] = '3306'
            config['DB_NAME'] = 'preclinitrain'
            config['DB_USER'] = 'appuser'
            config['DB_PASSWORD'] = secrets.token_hex(16)
            config['DB_ROOT_PASSWORD'] = secrets.token_hex(16)
            Colors.success("Configured internal MariaDB container")
        else:
            setup_external_database(config)
    else:
        print("1. SQLite (Simplest)")
        print("2. External MySQL/MariaDB")
        db_choice = input("Choice [1]: ").strip() or "1"
        
        if db_choice == '1':
            config['DB_TYPE'] = 'sqlite'
            Colors.success("Configured SQLite database")
        else:
            setup_external_database(config)

    # Email configuration
    print("\n--- Email Configuration (Optional) ---")
    print("Used for password resets and system notifications.")
    configure_email = input("Configure SMTP settings now? (y/N): ").strip().lower()
    if configure_email == 'y':
        mail_server = input("Mail server [smtp.gmail.com]: ").strip() or "smtp.gmail.com"
        mail_port = input("Mail port [587]: ").strip() or "587"
        mail_use_tls = input("Use TLS? (True/False) [True]: ").strip() or "True"
        mail_username = input("Mail username: ").strip()
        mail_password = input("Mail password: ").strip()

        config['MAIL_SERVER'] = mail_server
        config['MAIL_PORT'] = mail_port
        config['MAIL_USE_TLS'] = mail_use_tls
        config['MAIL_USERNAME'] = mail_username
        config['MAIL_PASSWORD'] = mail_password
    else:
        # If not configuring, ensure MAIL_SERVER is empty to disable mail
        config['MAIL_SERVER'] = ''
        Colors.info("SMTP disabled. You can configure it later in .env")

    # Precliniverse Integration
    print("\n--- Precliniverse Integration ---")
    if input("Configure Precliniverse integration? (y/N): ").lower() == 'y':
        default_pc_url = "http://precliniverse:8000" if deployment_mode == 'docker' else "http://localhost:8000"
        config['PC_API_URL'] = input(f"Precliniverse API URL [{default_pc_url}]: ").strip() or default_pc_url
        config['PC_API_KEY'] = input("Precliniverse SERVICE_API_KEY (from Precliniverse .env): ").strip()
        if not config['PC_API_KEY']:
            Colors.warning("No key provided. You can set it later with: python manage.py set-config PC_API_KEY <key>")
        else:
            Colors.success("Precliniverse integration configured!")
        config['PC_ENABLED'] = 'True'
    else:
        config['PC_ENABLED'] = 'False'
        Colors.info("Precliniverse integration disabled. Can be enabled later.")

    # Save configuration
    ConfigManager.save_env(config, backup=False)
    
    # Show important information
    print("\n" + "="*60)
    Colors.header("IMPORTANT: Save these credentials!")
    print("="*60)
    Colors.info(f"Admin Email: {admin_email}")
    Colors.info(f"Admin Password: {admin_password}")
    
    # Show inter-app keys
    Colors.info(f"\nInter-App Communication:")
    Colors.info(f"SERVICE_API_KEY: {config.get('SERVICE_API_KEY')}")
    Colors.info(f"SSO_SECRET_KEY: {config.get('SSO_SECRET_KEY')}")
    Colors.warning("Share these keys with Precliniverse for ecosystem integration!")
    
    if config.get('DB_TYPE') == 'mysql' and config.get('DB_HOST') == 'db':
        Colors.info(f"\nDatabase:")
        Colors.info(f"DB Password: {config.get('DB_PASSWORD')}")
        Colors.info(f"DB Root Password: {config.get('DB_ROOT_PASSWORD')}")
    print("="*60)
    
    Colors.success("\nSetup complete! Review and edit .env file as needed.")
    Colors.info("Next steps:")
    Colors.info("  1. Run: python manage.py deploy")
    Colors.info("  2. Access application at http://localhost:" + app_port)


def setup_external_database(config):
    """Setup external database configuration with connection testing."""
    config['DB_TYPE'] = 'mysql'
    db_host = input("Database host [localhost]: ").strip() or "localhost"
    db_port = input("Database port [3306]: ").strip() or "3306"
    db_name = input("Database name [preclinitrain]: ").strip() or "preclinitrain"
    db_user = input("Database user: ").strip()
    db_password = input("Database password: ").strip()
    
    config['DB_HOST'] = db_host
    config['DB_PORT'] = db_port
    config['DB_NAME'] = db_name
    config['DB_USER'] = db_user
    config['DB_PASSWORD'] = db_password
    
    # For Docker, also ask for root password
    if config.get('DEPLOYMENT_MODE') == 'docker':
        db_root_password = input("Database root password (for Docker container): ").strip()
        if db_root_password:
            config['DB_ROOT_PASSWORD'] = db_root_password
    
    # Test connection
    if confirm_action("Test database connection now?", default=True):
        Colors.info("Testing database connection...")
        success, msg = DatabaseManager.test_connection(config)
        if success:
            Colors.success(msg)
            # Offer to create database
            if confirm_action("Create database if it doesn't exist?", default=True):
                success_create, msg_create = DatabaseManager.create_database_if_not_exists(config)
                if success_create:
                    Colors.success(msg_create)
                else:
                    Colors.warning(msg_create)
        else:
            Colors.error(f"Connection failed: {msg}")
            if not confirm_action("Continue anyway?", default=False):
                Colors.warning("Returning to database configuration...")
                setup_external_database(config)
                return


# --- Deployment Functions ---

def deploy():
    """Deploy the application."""
    if not os.path.exists(ENV_FILE):
        Colors.error(".env file not found. Run 'python manage.py setup' first.")
        sys.exit(1)
    
    config = ConfigManager.load_env()
    mode = config.get('DEPLOYMENT_MODE', 'docker')
    
    if mode == 'docker':
        deploy_docker()
    else:
        deploy_native()


def deploy_docker():
    """Deploy using Docker Compose."""
    if not check_docker():
        return
    
    Colors.header("Docker Deployment")
    ensure_dirs()
    
    # Check network
    Colors.info("Checking Docker network...")
    result = run_command("docker network ls --format '{{.Name}}'", capture_output=True)
    if "lab_ecosystem" not in result:
        Colors.info("Creating lab_ecosystem network...")
        run_command("docker network create lab_ecosystem")
    
    # Build and start
    Colors.info("Building and starting services...")
    run_command("docker compose build")
    run_command("docker compose up -d")
    
    # Wait for services to be ready
    time.sleep(3)
    
    Colors.success("Deployment complete!")
    
    config = ConfigManager.load_env()
    port = config.get('APP_PORT', '5001')
    Colors.info(f"Application should be available at http://localhost:{port}")


def deploy_native():
    """Deploy in native mode."""
    Colors.header("Native Deployment")
    
    # Check for venv
    venv_dir = ".venv" if os.path.exists(".venv") else "venv"
    
    if not os.path.exists(venv_dir):
        Colors.info(f"Creating virtual environment...")
        import venv as venv_module
        venv_module.create(venv_dir, with_pip=True)
    
    # Determine python and pip paths
    if IS_WINDOWS:
        python_exec = os.path.join(venv_dir, "Scripts", "python.exe")
        pip_exec = os.path.join(venv_dir, "Scripts", "pip.exe")
    else:
        python_exec = os.path.join(venv_dir, "bin", "python")
        pip_exec = os.path.join(venv_dir, "bin", "pip")
    
    # Install dependencies
    Colors.info("Installing dependencies...")
    run_command(f'"{pip_exec}" install -r requirements.txt')
    
    # Ensure directories
    ensure_dirs()
    
    # Database initialization
    Colors.info("Initializing database...")
    
    # Check if migrations are properly set up (env.py must exist)
    migrations_env = os.path.join("migrations", "env.py")
    
    if os.path.exists(migrations_env):
        # Migrations exist, run upgrade
        Colors.info("Running database migrations...")
        run_command(f'"{python_exec}" -m flask db upgrade', check=False)
    else:
        # No migrations - check if we need to initialize them
        if os.path.exists("migrations"):
            # migrations folder exists but no env.py - initialize
            Colors.info("Initializing Flask-Migrate...")
            # Remove empty migrations folder
            shutil.rmtree("migrations")
        
        # Try to initialize with flask db init
        Colors.info("Setting up database migrations...")
        result = run_command(f'"{python_exec}" -m flask db init', check=False, capture_output=True)
        
        if result and "Error" not in str(result):
            # Generate initial migration
            Colors.info("Creating initial migration...")
            run_command(f'"{python_exec}" -m flask db migrate -m "Initial migration"', check=False)
            
            # Apply migration
            Colors.info("Applying migrations...")
            run_command(f'"{python_exec}" -m flask db upgrade', check=False)
        else:
            # Fallback: Try direct table creation via app initialization
            Colors.info("Creating database tables directly...")
            # This relies on the app's own db.create_all() logic
            run_command(f'"{python_exec}" -c "from app import create_app, db; app = create_app(); app.app_context().push(); db.create_all(); print(\'Database tables created.\')"', check=False)
    
    Colors.success("Native deployment complete!")
    Colors.info("To start the application:")
    Colors.info("  python manage.py start")
    Colors.info("Or manually with gunicorn:")
    config = ConfigManager.load_env()
    port = config.get('APP_PORT', '5001')
    Colors.info(f"  {python_exec} -m gunicorn -w 4 -b 0.0.0.0:{port} 'app:create_app()'")


# --- Service Management ---

def start():
    """Start the application."""
    config = ConfigManager.load_env()
    mode = config.get('DEPLOYMENT_MODE', 'docker')
    
    if mode == 'docker':
        if not check_docker():
            return
        Colors.info("Starting services...")
        run_command("docker compose up -d")
        Colors.success("Services started")
    else:
        start_native()


def start_native():
    """Start application in native mode using gunicorn."""
    Colors.header("Starting Native Application")
    
    config = ConfigManager.load_env()
    port = config.get('APP_PORT', '5001')
    
    # Check for venv
    venv_dir = ".venv" if os.path.exists(".venv") else "venv"
    if IS_WINDOWS:
        python_exec = os.path.join(venv_dir, "Scripts", "python.exe")
    else:
        python_exec = os.path.join(venv_dir, "bin", "python")
    
    # Check if already running
    pid_file = os.path.join("logs", "gunicorn.pid")
    if os.path.exists(pid_file):
        try:
            with open(pid_file, 'r') as f:
                pid = int(f.read().strip())
            # Check if process is running
            if IS_WINDOWS:
                result = subprocess.run(['tasklist', '/FI', f'PID eq {pid}', '/NH'], capture_output=True, text=True)
                if str(pid) in result.stdout:
                    Colors.warning(f"Application already running (PID: {pid})")
                    return
            else:
                os.kill(pid, 0)
                Colors.warning(f"Application already running (PID: {pid})")
                return
        except (ProcessLookupError, OSError, ValueError):
            pass  # Process not running, continue
    
    # Ensure logs directory exists
    if not os.path.exists("logs"):
        os.makedirs("logs")
    
    Colors.info(f"Starting on port {port}...")
    
    if IS_WINDOWS:
        # Windows: Use waitress instead of gunicorn
        Colors.info("Using waitress on Windows...")
        log_file = os.path.join("logs", "app.log")
        pid_file = os.path.join("logs", "app.pid")
        
        # Prepare command
        cmd = [python_exec, "-c", f"from waitress import serve; from app import create_app; serve(create_app(), host='0.0.0.0', port={port})"]
        
        try:
            with open(log_file, "a") as log:
                # CREATE_NEW_PROCESS_GROUP (0x00000200) allows the child to survive Ctrl+C
                process = subprocess.Popen(
                    cmd,
                    stdout=log,
                    stderr=log,
                    creationflags=subprocess.CREATE_NEW_PROCESS_GROUP
                )
            
            with open(pid_file, 'w') as f:
                f.write(str(process.pid))
                
            Colors.success(f"Started (PID: {process.pid})")
            Colors.info(f"App available at http://localhost:{port}")
            
            # Switch to live logs
            logs_native()
            
        except PermissionError:
             Colors.error(f"Permission denied accessing '{log_file}'")
             Colors.warning("The file is locked by another process.")
             Colors.info("Tip: Try running Option 2 (Stop Application) to force-kill zombie processes.")
        except Exception as e:
            Colors.error(f"Failed to start: {e}")

    else:
        # Linux/Mac: Use gunicorn
        log_file = os.path.join("logs", "gunicorn.log")
        error_log = os.path.join("logs", "gunicorn_error.log")
        
        cmd = f'"{python_exec}" -m gunicorn -w 4 -b 0.0.0.0:{port} --pid "{pid_file}" --access-logfile "{log_file}" --error-logfile "{error_log}" --daemon "app:create_app()"'
        run_command(cmd, check=False)
        
        time.sleep(2)
        
        if os.path.exists(pid_file):
            with open(pid_file, 'r') as f:
                pid = f.read().strip()
            Colors.success(f"Application started (PID: {pid})")
            Colors.info(f"URL: http://localhost:{port}")
            logs_native()
        else:
            Colors.error("Failed to start. Check logs for details.")
            Colors.info(f"Error log: {error_log}")


def stop():
    """Stop the application."""
    config = ConfigManager.load_env()
    mode = config.get('DEPLOYMENT_MODE', 'docker')
    
    if mode == 'docker':
        if not check_docker():
            return
        Colors.info("Stopping services...")
        run_command("docker compose stop")
        Colors.success("Services stopped")
    else:
        stop_native()


def stop_native():
    """Stop native application."""
    Colors.info("Stopping application...")
    
    # Check both standard locations
    pid_files = [
        os.path.join("logs", "app.pid"),      # Windows/Waitress
        os.path.join("logs", "gunicorn.pid")  # Linux/Gunicorn
    ]
    
    stopped = False
    
    for pid_file in pid_files:
        if os.path.exists(pid_file):
            try:
                with open(pid_file, 'r') as f:
                    pid = int(f.read().strip())
                
                Colors.info(f"Stopping PID {pid} from {os.path.basename(pid_file)}...")
                
                if IS_WINDOWS:
                    subprocess.run(f'taskkill /PID {pid} /F', shell=True, capture_output=True)
                else:
                    os.kill(pid, 15)  # SIGTERM
                    time.sleep(2)
                    try:
                        os.kill(pid, 0)  # Check if still running
                        os.kill(pid, 9)  # Force kill with SIGKILL
                    except ProcessLookupError:
                        pass  # Already dead
                
                os.remove(pid_file)
                Colors.success(f"Application stopped (PID: {pid})")
                stopped = True
            except (ValueError, ProcessLookupError, OSError) as e:
                Colors.warning(f"Could not stop process from {pid_file}: {e}")
                if os.path.exists(pid_file):
                    os.remove(pid_file)

    if not stopped:
        # Fallback: Check if port is still in use and kill that process (Zombie cleanup)
        config = ConfigManager.load_env()
        port = config.get('APP_PORT', '5001')
        
        killed_orphans = kill_process_by_port(port)
        
        if killed_orphans:
            Colors.success(f"Force killed orphaned process(es) on port {port}")
            # Give OS a moment to release file handles
            time.sleep(1)
        else:
            if not IS_WINDOWS:
                # Fallback for Linux gunicorn
                Colors.info("Looking for gunicorn processes...")
                result = subprocess.run("pgrep -f 'gunicorn.*app:create_app'", shell=True, capture_output=True, text=True)
                if result.stdout.strip():
                    pids = result.stdout.strip().split('\n')
                    for pid in pids:
                        try:
                            os.kill(int(pid), 15)
                            Colors.info(f"Stopped PID {pid}")
                        except:
                            pass
                    Colors.success("Application stopped")
                else:
                    Colors.info("No running application found")
            else:
                if not killed_orphans:
                    Colors.warning("No running application found (checked PIDs and Port)")


def kill_process_by_port(port):
    """Kill process listening on a specific port."""
    if IS_WINDOWS:
        try:
            # Find PID using netstat
            cmd = f'netstat -ano | findstr :{port}'
            result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
            if not result.stdout:
                return False
            
            lines = result.stdout.strip().split('\n')
            killed = False
            for line in lines:
                # Expected format: TCP    0.0.0.0:5001    0.0.0.0:0    LISTENING    1234
                # Note: findstr might match partial ports, so verify alignment if possible, 
                # but simplistic approach usually works for dev envs.
                parts = line.split()
                if len(parts) >= 5:
                    pid = parts[-1]
                    state = parts[3] 
                    if pid.isdigit() and int(pid) > 0:
                        # Only kill if it looks like a listener process or we are desperate
                        try:
                            subprocess.run(f'taskkill /PID {pid} /F', shell=True, capture_output=True)
                            killed = True
                        except:
                            pass
            return killed
        except:
            return False
    else:
        # Linux
        try:
             # Try fuser
             cmd = f"fuser -k {port}/tcp"
             res = subprocess.run(cmd, shell=True, capture_output=True)
             if res.returncode == 0:
                 return True
             
             # Try lsof
             cmd = f"lsof -t -i:{port} | xargs -r kill"
             subprocess.run(cmd, shell=True)
             return True
        except:
             return False


def restart():
    """Restart the application."""
    stop()
    time.sleep(2)
    start()


def logs():
    """Show application logs."""
    config = ConfigManager.load_env()
    mode = config.get('DEPLOYMENT_MODE', 'docker')
    
    if mode == 'docker':
        if not check_docker():
            return
        Colors.info("Following logs (Ctrl+C to stop)...")
        run_command("docker compose logs -f")
    else:
        logs_native()


def logs_native():
    """Show native application logs."""
    log_files = [
        os.path.join("logs", "gunicorn.log"),
        os.path.join("logs", "app.log")
    ]
    
    # Sort files by modification time, newest last, but prefer app.log or gunicorn.log over others
    existing_logs = [f for f in log_files if os.path.exists(f)]
    
    if not existing_logs:
        Colors.warning("No log files found in logs/")
        return
    
    target_log = existing_logs[-1] # Pick the last one (usually app.log on windows)
    Colors.info(f"Tailing {target_log} (Ctrl+C to exit logs)...")
    
    try:
        if IS_WINDOWS:
            # Python implementation of tail -f
            with open(target_log, 'r') as f:
                # Seek to end
                f.seek(0, 2)
                while True:
                    line = f.readline()
                    if not line:
                        time.sleep(0.1)
                        continue
                    print(line, end='')
        else:
            # Linux: Use tail command
            subprocess.run(['tail', '-f', target_log])
    except KeyboardInterrupt:
        print() # Newline
        Colors.info("Stopped watching logs. Application is still running.")


def create_admin():
    """Create admin user."""
    config = ConfigManager.load_env()
    mode = config.get('DEPLOYMENT_MODE', 'docker')
    
    if mode == 'docker':
        if not check_docker():
            return
        run_command("docker compose exec web flask create-admin")
    else:
        Colors.warning("Native create-admin not yet implemented.")


def link_ecosystem():
    """Configure ecosystem integration with Precliniverse."""
    print_banner("Ecosystem Integration Setup")
    
    if not os.path.exists(ENV_FILE):
        Colors.error(f"{ENV_FILE} not found. Run 'setup' first.")
        sys.exit(1)
    
    config = ConfigManager.load_env()
    
    # Show current keys
    Colors.info("Current PrecliniTrain keys for ecosystem:")
    Colors.info(f"  SERVICE_API_KEY: {config.get('SERVICE_API_KEY', 'Not set')}")
    Colors.info(f"  SSO_SECRET_KEY: {config.get('SSO_SECRET_KEY', 'Not set')}")
    
    if not config.get('SERVICE_API_KEY'):
        config['SERVICE_API_KEY'] = secrets.token_hex(32)
        Colors.success(f"Generated new SERVICE_API_KEY: {config['SERVICE_API_KEY']}")
    
    if not config.get('SSO_SECRET_KEY'):
        config['SSO_SECRET_KEY'] = secrets.token_hex(32)
        Colors.success(f"Generated new SSO_SECRET_KEY: {config['SSO_SECRET_KEY']}")
    
    # Configure Precliniverse connection
    print("\n--- Precliniverse Connection ---")
    default_url = config.get('PC_API_URL', 'http://localhost:8000')
    config['PC_API_URL'] = input(f"Precliniverse API URL [{default_url}]: ").strip() or default_url
    
    pc_key = input("Precliniverse SERVICE_API_KEY (from Precliniverse .env): ").strip()
    if pc_key:
        config['PC_API_KEY'] = pc_key
        config['PC_ENABLED'] = 'True'
        Colors.success("Precliniverse integration configured!")
    else:
        Colors.warning("No key provided. Integration not enabled.")
        config['PC_ENABLED'] = 'False'
    
    # Save
    ConfigManager.save_env(config)
    
    # Summary
    print("\n" + "="*60)
    Colors.header("Ecosystem Keys Summary")
    print("="*60)
    Colors.info("Copy these to Precliniverse .env:")
    Colors.info(f"  TM_API_KEY={config.get('SERVICE_API_KEY')}")
    Colors.info(f"  TM_API_URL=http://<this-server>:{config.get('APP_PORT', '5001')}")
    print("="*60)


def bump(part='patch'):
    """Bump the version number."""
    version_file = "VERSION"
    if not os.path.exists(version_file):
        with open(version_file, "w") as f:
            f.write("1.0.0")
        Colors.success("Created VERSION file with 1.0.0")
        return

    with open(version_file, "r") as f:
        current_version = f.read().strip()

    try:
        # Handle versions like 1.0.0-rc2
        base_version = current_version.split('-')[0]
        suffix = ""
        if '-' in current_version:
             suffix = "-" + current_version.split('-')[1]

        v_parts = base_version.split('.')
        while len(v_parts) < 3:
            v_parts.append("0")
        
        major = int(v_parts[0])
        minor = int(v_parts[1])
        patch = int(v_parts[2])

        if part == 'major':
            major += 1
            minor = 0
            patch = 0
        elif part == 'minor':
            minor += 1
            patch = 0
        else: # patch
            patch += 1

        new_version = f"{major}.{minor}.{patch}"
        # Suffixes are usually lost on bump unless we decide otherwise
        # For this simple implementation, we'll clear the suffix on bump
        
        with open(version_file, "w") as f:
            f.write(new_version)
        
        Colors.success(f"Version bumped: {current_version} -> {new_version}")
    except Exception as e:
        Colors.error(f"Failed to bump version: {e}")


def get_app_status():
    """Get formatted application status."""
    config = ConfigManager.load_env()
    mode = config.get('DEPLOYMENT_MODE', 'docker')

    if mode == 'docker':
        # Check docker status
        try:
             subprocess.run("docker info", shell=True, capture_output=True, check=True)
             pass
        except:
             return f"{Colors.FAIL}Docker Error{Colors.ENDC}"

        # Check if containers are running
        res = run_command("docker compose ps --services --filter status=running", capture_output=True, check=False)
        if res.stdout.strip():
            return f"{Colors.OKGREEN}Running (Docker){Colors.ENDC}"
        return f"{Colors.WARNING}Stopped (Docker){Colors.ENDC}"
    else:
        # Native status
        pid_files = [
            os.path.join("logs", "app.pid"),
            os.path.join("logs", "gunicorn.pid")
        ]
        for pf in pid_files:
            if os.path.exists(pf):
                try:
                    with open(pf, 'r') as f:
                        pid = int(f.read().strip())
                    
                    is_running = False
                    if IS_WINDOWS:
                        # Check tasklist
                        res = subprocess.run(['tasklist', '/FI', f'PID eq {pid}', '/NH'], capture_output=True, text=True)
                        if str(pid) in res.stdout:
                            is_running = True
                    else:
                        try:
                            os.kill(pid, 0)
                            is_running = True
                        except OSError:
                            pass
                    
                    if is_running:
                        server_type = "Waitress" if IS_WINDOWS else "Gunicorn"
                        return f"{Colors.OKGREEN}Running (PID: {pid}, {server_type}){Colors.ENDC}"
                except:
                    pass
        
        return f"{Colors.WARNING}Stopped{Colors.ENDC}"


def interactive_menu():
    """Show interactive menu."""
    while True:
        status = get_app_status()
        print_banner(f"PrecliniTrain Manager\n   Status: {status}")
        
        print("1. Start/Restart Application")
        print("2. Stop Application")
        print("3. View Logs")
        print("4. Deploy (Docker/Native)")
        print("5. Run Setup Wizard")
        print("6. Create Admin User")
        print("7. Check Health")
        print("8. Create Demo Data")
        print("9. Bump Version (Patch)")
        print("0. Exit")
        
        choice = input(f"\n{Colors.OKCYAN}Select an option:{Colors.ENDC} ").strip()
        
        try:
            if choice == '1': 
                if "Running" in status:
                    restart()
                else:
                    start()
            elif choice == '2': stop()
            elif choice == '3': logs()
            elif choice == '4': deploy()
            elif choice == '5': setup_env_file()
            elif choice == '6': create_admin()
            elif choice == '7': 
                if platform.system().lower() == 'windows':
                    os.system('cls')
                else:
                    os.system('clear')
                subprocess.run([sys.executable, "manage.py", "health"])
                input("\nPress Enter to continue...")
                
            elif choice == '8':
                if platform.system().lower() == 'windows':
                    os.system('cls')
                else:
                    os.system('clear')
                from app import create_app
                from app.cli.demo_data import create_demo_data_command
                app = create_app()
                with app.app_context():
                    create_demo_data_command()
                input("\nDemo data generated. Press Enter to continue...")
                
            elif choice == '9':
                bump('patch')
                input("\nPress Enter to continue...")

            elif choice == '0': 
                sys.exit(0)
            else:
                Colors.error("Invalid choice")
                time.sleep(1)
                
        except KeyboardInterrupt:
            print("\n")
            continue


# --- Main ---
def main():
    parser = argparse.ArgumentParser(description="PrecliniTrain CLI")
    subparsers = parser.add_subparsers(dest='command', help='Available commands')

    # Setup command
    subparsers.add_parser('setup', help='Initial setup wizard')

    # Deployment commands
    subparsers.add_parser('deploy', help='Deploy application')
    subparsers.add_parser('start', help='Start the application')
    subparsers.add_parser('stop', help='Stop the application')
    subparsers.add_parser('restart', help='Restart the application')
    subparsers.add_parser('logs', help='Show application logs')
    
    # Health & Diagnostics
    subparsers.add_parser("health", help="Run comprehensive health checks and diagnostics")
    subparsers.add_parser("check-ports", help="Verify port availability")
    subparsers.add_parser("check-db", help="Test database connectivity")
    
    # Configuration Management
    config_parser = subparsers.add_parser("set-config", help="Set single .env parameter")
    config_parser.add_argument("key", help="Configuration key")
    config_parser.add_argument("value", help="Configuration value")
    config_parser.add_argument("--no-backup", action="store_true", help="Don't create backup")
    
    get_parser = subparsers.add_parser("config-get", help="Get single .env parameter value")
    get_parser.add_argument("key", help="Configuration key")

    # Admin command
    subparsers.add_parser('create-admin', help='Create admin user')
    
    # Ecosystem integration
    subparsers.add_parser('link-ecosystem', help='Configure Precliniverse integration')

    # Demo Data
    subparsers.add_parser('create-demo-data', help='Generate demo data for testing')

    # Versioning
    bump_parser = subparsers.add_parser('bump', help='Bump application version')
    bump_parser.add_argument('part', choices=['major', 'minor', 'patch'], default='patch', nargs='?', 
                             help='Part of the version to bump (default: patch)')

    args = parser.parse_args()

    if not args.command:
        interactive_menu()
        return

    # Execute command
    if args.command == 'setup':
        setup_env_file()
    elif args.command == 'deploy':
        deploy()
    elif args.command == 'start':
        start()
    elif args.command == 'stop':
        stop()
    elif args.command == 'restart':
        restart()
    elif args.command == 'logs':
        logs()
    elif args.command == 'create-admin':
        create_admin()
    elif args.command == 'link-ecosystem':
        link_ecosystem()
    elif args.command == 'create-demo-data':
        from app import create_app
        from app.cli.demo_data import create_demo_data_command
        app = create_app()
        with app.app_context():
            create_demo_data_command()
    
    elif args.command == 'bump':
        bump(args.part)
    
    # Configuration management
    elif args.command == "set-config":
        if not os.path.exists(ENV_FILE):
            Colors.error(f"{ENV_FILE} not found. Run 'setup' first.")
            sys.exit(1)
        
        valid, msg = ConfigManager.validate_value(args.key, args.value)
        if not valid:
            Colors.error(f"Validation failed: {msg}")
            sys.exit(1)
        
        old_value = ConfigManager.set_value(args.key, args.value, backup=not args.no_backup)
        if old_value:
            Colors.info(f"Changed {args.key}: {old_value} → {args.value}")
        else:
            Colors.success(f"Set {args.key} = {args.value}")
    
    elif args.command == "config-get":
        if not os.path.exists(ENV_FILE):
            Colors.error(f"{ENV_FILE} not found. Run 'setup' first.")
            sys.exit(1)
        
        value = ConfigManager.get_value(args.key)
        if value is not None:
            print(f"{args.key}={value}")
        else:
            Colors.warning(f"{args.key} not found in {ENV_FILE}")
            sys.exit(1)
    
    # Health checks
    elif args.command == "check-ports":
        print_banner("Port Availability Check")
        
        config = ConfigManager.load_env()
        app_port = config.get('APP_PORT', '5001')
        
        table = StatusTable()
        
        if PortManager.check_port_available(app_port):
            table.add_row(f"Application Port ({app_port})", "Available", "Ready to use")
        else:
            info = PortManager.get_port_info(app_port)
            table.add_row(f"Application Port ({app_port})", "Unavailable", info[:47])
            
            alternatives = PortManager.suggest_alternative_ports(app_port)
            if alternatives:
                Colors.warning(f"Port {app_port} is in use. Suggested alternatives:")
                for alt in alternatives:
                    Colors.info(f"  - {alt}")
        
        table.render()
    
    elif args.command == "check-db":
        print_banner("Database Connectivity Check")
        
        config = ConfigManager.load_env()
        
        with Spinner("Testing database connection"):
            success, message = DatabaseManager.test_connection(config)
        
        if success:
            Colors.success(f"Database: {message}")
            
            if config.get('DB_TYPE') in ['mysql', 'mariadb']:
                success_create, msg_create = DatabaseManager.create_database_if_not_exists(config)
                if success_create:
                    Colors.success(msg_create)
                else:
                    Colors.warning(msg_create)
        else:
            Colors.error(f"Database connection failed: {message}")
            
            if config.get('DB_TYPE') in ['mysql', 'mariadb']:
                Colors.info("Troubleshooting tips:")
                Colors.info("  1. Verify database server is running")
                Colors.info("  2. Check DB_HOST, DB_PORT, DB_USER, DB_PASSWORD in .env")
                Colors.info("  3. Ensure user has access to the database")
                Colors.info("  4. For Docker: check container is running")
            sys.exit(1)
    
    elif args.command == "health":
        print_banner("System Health Check")
        
        table = StatusTable()
        config = ConfigManager.load_env()
        
        issues_found = []
        fixes_suggested = []
        
        # 1. Check Configuration
        if os.path.exists(ENV_FILE):
             table.add_row("Configuration", "OK", f"{len(config)} parameters loaded")
        else:
             table.add_row("Configuration", "Missing", "Run 'setup' to create")
             issues_found.append("No .env configuration file")
             fixes_suggested.append("Run: python manage.py setup")

        # 2. Check Ports
        app_port = config.get('APP_PORT', '5001')
        if PortManager.check_port_available(app_port):
            table.add_row(f"Port {app_port}", "Available", "")
        else:
            if PortManager.is_app_using_port(app_port, config):
                table.add_row(f"Port {app_port}", "Active", "Used by this application")
            else:
                table.add_row(f"Port {app_port}", "In Use", "Conflict with other process")
                issues_found.append(f"Port {app_port} is already in use by another process")
                alternatives = PortManager.suggest_alternative_ports(app_port, 2)
                if alternatives:
                    fixes_suggested.append(f"Use alternative port: python manage.py set-config APP_PORT {alternatives[0]}")
        
        # 3. Check Database
        db_success, db_msg = DatabaseManager.test_connection(config)
        if db_success:
            table.add_row("Database", "Connected", db_msg)
        else:
            table.add_row("Database", "Failed", db_msg[:47])
            issues_found.append(f"Database not accessible: {db_msg}")
            if config.get('DB_TYPE') in ['mysql', 'mariadb']:
                fixes_suggested.append("1. Start database: docker-compose up -d db (if using Docker)")
                fixes_suggested.append("2. Verify credentials in .env file")
                fixes_suggested.append("3. Run: python manage.py check-db")

        # 4. Check Directories
        missing_dirs = [d for d in REQUIRED_DIRS if not os.path.exists(d)]
        if missing_dirs:
            table.add_row("Directories", "Warning", f"Missing: {', '.join(missing_dirs)}")
            issues_found.append(f"Missing directories: {', '.join(missing_dirs)}")
            fixes_suggested.append("Directories will be created automatically on deploy")
        else:
            table.add_row("Directories", "OK", "All present")
        
        # 5. Check Docker (if in docker mode)
        if config.get('DEPLOYMENT_MODE') == 'docker':
            try:
                result = subprocess.run("docker info", shell=True, capture_output=True, timeout=3)
                if result.returncode == 0:
                    table.add_row("Docker", "Running", "")
                else:
                    table.add_row("Docker", "Error", "Not accessible")
                    issues_found.append("Docker is not running or not accessible")
                    fixes_suggested.append("Start Docker Desktop or Docker daemon")
            except:
                table.add_row("Docker", "Error", "Not found or not running")
                issues_found.append("Docker not found")
                fixes_suggested.append("Install Docker: https://docker.com/get-started")
        
        # Render Table
        table.render()
        
        # Render Diagnostics if issues found
        if issues_found:
            print("\n" + "="*60)
            Colors.header(f"Diagnostics: Found {len(issues_found)} issue(s)")
            print("="*60)
            for i, issue in enumerate(issues_found, 1):
                Colors.error(f"  {i}. {issue}")
            
            print()
            Colors.info("Suggested fixes:")
            for fix in fixes_suggested:
                Colors.info(f"  • {fix}")
        else:
            Colors.success("All systems operational. No issues detected.")
    
    elif args.command == "doctor":
        print_banner("System Diagnostics")
        
        issues_found = []
        fixes_suggested = []
        
        config = ConfigManager.load_env()
        
        # Check .env
        if not os.path.exists(ENV_FILE):
            issues_found.append("No .env configuration file")
            fixes_suggested.append("Run: python manage.py setup")
        
        # Check port conflicts
        app_port = config.get('APP_PORT', '5001')
        if not PortManager.check_port_available(app_port):
            if PortManager.is_app_using_port(app_port, config):
                 # This is fine, it's us!
                 pass
            else:
                issues_found.append(f"Port {app_port} is already in use by another process")
                alternatives = PortManager.suggest_alternative_ports(app_port, 2)
                if alternatives:
                    fixes_suggested.append(f"Use alternative port: python manage.py set-config APP_PORT {alternatives[0]}")
        
        # Check database
        db_success, db_msg = DatabaseManager.test_connection(config)
        if not db_success:
            issues_found.append(f"Database not accessible: {db_msg}")
            if config.get('DB_TYPE') in ['mysql', 'mariadb']:
                fixes_suggested.append("1. Start database: docker-compose up -d db (if using Docker)")
                fixes_suggested.append("2. Verify credentials in .env file")
                fixes_suggested.append("3. Run: python manage.py check-db")
        
        # Check directories
        missing_dirs = [d for d in REQUIRED_DIRS if not os.path.exists(d)]
        if missing_dirs:
            issues_found.append(f"Missing directories: {', '.join(missing_dirs)}")
            fixes_suggested.append("Directories will be created automatically on deploy")
        
        # Check Docker (if docker mode)
        if config.get('DEPLOYMENT_MODE') == 'docker':
            try:
                result = subprocess.run("docker info", shell=True, capture_output=True, timeout=3)
                if result.returncode != 0:
                    issues_found.append("Docker is not running or not accessible")
                    fixes_suggested.append("Start Docker Desktop or Docker daemon")
            except:
                issues_found.append("Docker not found")
                fixes_suggested.append("Install Docker: https://docker.com/get-started")
        
        # Report
        if issues_found:
            Colors.warning(f"Found {len(issues_found)} issue(s):")
            for i, issue in enumerate(issues_found, 1):
                Colors.error(f"  {i}. {issue}")
            
            print()
            Colors.info("Suggested fixes:")
            for fix in fixes_suggested:
                Colors.info(f"  • {fix}")
        else:
            Colors.success("No issues detected! System looks healthy.")
            Colors.info("You can proceed with: python manage.py deploy")


if __name__ == '__main__':
    main()
