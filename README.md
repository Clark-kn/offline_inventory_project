# Kaliwabo Inventory

**Kaliwabo Software Studio**

An offline Windows desktop inventory management system for tracking products, purchasing, sales, stock movements, damaged goods and reports. It uses a local SQLite database and does not require a cloud account or hosted database for normal inventory operations.

Built with Python 3.11+, PySide6, SQLAlchemy, SQLite, Alembic, ReportLab, openpyxl and PyInstaller.

## Features

### Master Data
- Products: SKU, barcode, name, category, unit, selling price, reorder level, location and active/inactive status.
- Categories, units and locations.
- Suppliers and customers.
- Records referenced by transaction history can be deactivated instead of hard-deleted.

### Inventory and Transactions
- Purchases / Stock In with multiple product lines.
- Sales / Stock Out with multiple product lines.
- Purchase Orders.
- Stock Adjustments with a mandatory reason.
- Damaged Goods recording and management.
- Stock Ledger with user attribution and related transaction references where available.
- Database transactions protect multi-item stock operations from partial updates.
- Normal stock-out operations cannot reduce stock below zero.

### Dashboard and Reports
- Dashboard indicators for active products, stock value, low-stock items, out-of-stock items and recent movements.
- Current stock, low-stock, out-of-stock and date-ranged stock movement reports.
- PDF and Excel exports.

### Security and User Accounts
- Login required.
- Passwords hashed using PBKDF2-SHA256 with per-user random salts.
- Four roles: Admin, Manager, Operator and Viewer.
- Authorization enforced in application services and the user interface where applicable.
- Operators cannot override saved selling prices during sales.
- Damaged Goods deletion is Admin-only and recorded in the Audit Log.
- Audit records cover important authentication, user and inventory actions.
- First-run setup creates the initial administrator account.

### Local Data and Backups
- Local SQLite database.
- Database location selected during first-run setup, outside the application installation directory.
- Configuration stored separately from the installed application.
- Automatic daily backups with configurable retention (default: 14 backups).
- Manual backup and restore with database integrity checking.
- Authorized administrators can manage database and backup locations.
- Uninstallation preserves the database, configuration and backups.

### Database Migrations
- Alembic schema migrations run automatically during application startup.
- Fresh installations create the current schema.
- Existing databases are upgraded through migrations rather than being recreated.

### Windows Packaging
- PyInstaller builds the application into a Windows application folder containing the executable and supporting files.
- The application includes self-installation support.
- Inno Setup builds a Windows setup executable for per-user installation.
- The standard installation does not require administrator privileges.
- Uninstallation removes the installed application while preserving user data.

## Roles and Permissions

| Screen / Function | Admin | Manager | Operator | Viewer |
|---|:---:|:---:|:---:|:---:|
| Dashboard | Yes | Yes | Yes | Yes |
| Products | Yes | Yes | Yes | Read-only |
| Categories / Units / Locations | Yes | Yes | No | No |
| Suppliers / Customers | Yes | Yes | No | No |
| Purchases / Sales / Adjustments | Yes | Yes | Yes | No |
| Purchase Orders | Yes | Yes | Yes | No |
| Damaged Goods | Yes | Yes | Yes | No |
| Stock Ledger | Yes | Yes | Yes | No |
| Reports | Yes | Yes | Yes | No |
| Users | Yes | No | No | No |
| Audit Log | Yes | No | No | No |
| Application Settings | Yes | No | No | No |

Additional restrictions:
- Viewer access is limited to Dashboard and read-only Products.
- Operators cannot override saved selling prices during sales.
- Damaged Goods deletion is Admin-only and recorded in the Audit Log.

## Getting Started — Development

Requirements:
- Windows
- Python 3.11 or newer
- Git

Clone the repository:

    git clone https://github.com/P-Sudhakar-tech/offline_inventory_project.git
    cd offline_inventory_project

Create and activate a virtual environment:

    python -m venv .venv
    .\.venv\Scripts\Activate.ps1

Install dependencies:

    python -m pip install -r requirements.txt

Run the application:

    python main.py

Alternatively, use run_app.bat after installing dependencies.

On first launch, choose the database location, create the administrator account and sign in.

## Running Tests

Run the complete automated test suite:

    .\.venv\Scripts\python.exe -m pytest -q

The test suite covers authentication, authorization, master data, purchases, sales, stock movements, damaged goods, purchase orders, reports, audit logging, migrations, backup and restore, application paths, timezone handling and application hardening.

The latest recorded full regression run for this release candidate completed with 265 passed. Run the tests again after making code changes.

## Building the Windows Application

Build the PyInstaller application folder:

    .\.venv\Scripts\python.exe -m PyInstaller inventory_manager.spec --noconfirm

Output:

    dist\InventoryManager\InventoryManager.exe

This is a packaged application folder, not a standalone one-file executable.

## Building the Inno Setup Installer

Install Inno Setup 7, then compile the installer:

    & "E:\Programs\Inno Setup 7\ISCC.exe" installer.iss

The installer output location is defined in installer.iss.

## Project Structure

    app/
    ├── backup/         Backup-related functionality
    ├── config/         Application configuration and data paths
    ├── data/           Database models, sessions and Alembic migrations
    ├── domain/         Domain logic
    ├── reports/        Report generation and export helpers
    ├── security/       Permissions and authorization helpers
    ├── services/       Business logic and application services
    ├── setup/          Application self-installation support
    ├── ui/             PySide6 windows, dialogs and tabs
    ├── utils/          Shared utilities
    └── viewmodels/     UI view models

    tests/              Automated pytest suite
    resources/          Application resources and stylesheets
    main.py             Application entry point
    alembic.ini         Alembic configuration
    inventory_manager.spec
    installer.iss       Inno Setup installer definition
    requirements.txt    Python dependencies
    run_app.bat         Development launch helper
## Data and Security Notes

- The application is designed for local use on a Windows computer.
- Database, configuration and backup files are separate from the program installation.
- Backups should periodically be copied to another safe location. A backup on the same physical drive does not protect against drive failure.
- Application roles do not replace Windows account security or physical protection of the computer.
- This is a desktop inventory application, not a multi-computer synchronized or cloud-hosted system.

## License

MIT License. See LICENSE.
