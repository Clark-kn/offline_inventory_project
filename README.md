# Kaliwabo Inventory

**Kaliwabo Software Studio**

An offline Windows desktop application for managing inventory, purchasing, sales, stock movements, damaged goods and reports.

Kaliwabo Inventory is intended for businesses that need a practical, locally operated inventory system without depending on a cloud account or hosted database for normal operations.

**Version:** 1.0.0
**Platform:** Windows
**Application type:** Offline desktop software
**Technology:** Python, PySide6, SQLAlchemy, SQLite

---

## Project Background and Attribution

Kaliwabo Inventory is a rebranded and modified fork of the open-source **Offline Inventory Management System** originally created by **Sudhakar Ponugoti**.

- **Original project:** [P-Sudhakar-tech/offline_inventory_project](https://github.com/P-Sudhakar-tech/offline_inventory_project)
- **Original author:** Sudhakar Ponugoti
- **Original licence:** MIT
- **Kaliwabo fork:** [Clark-kn/offline_inventory_project](https://github.com/Clark-kn/offline_inventory_project)

The original project provided the application foundation and existing functionality. This repository preserves that lineage and documents the additional work carried out for the Kaliwabo-branded release.

### Work carried out for the Kaliwabo release

The work in this fork includes:

- Rebranding the application interface and Windows installer as **Kaliwabo Inventory**.
- Introducing **Kaliwabo Software Studio** as the product publisher identity.
- Updating installation branding while retaining the established application identity and installation directory for upgrade compatibility.
- Refining role-based access and application permissions.
- Enforcing saved selling-price restrictions for operators.
- Restricting damaged-goods deletion to administrators and recording deletions in the audit log.
- Preparing and testing a Windows installation package.
- Running regression tests and validating the branded application through a separate Windows test account.

This is a fork with additional modifications, not a claim of sole authorship of the original application.

---

## Features

### Inventory and master data

- Product records with SKU, barcode, category, unit, selling price and reorder level.
- Categories, units and locations.
- Supplier and customer records.
- Active and inactive record management.
- Purchase and stock-in transactions.
- Sales and stock-out transactions.
- Purchase orders.
- Stock adjustments with mandatory reasons.
- Damaged-goods recording and management.
- Stock ledger with user attribution and related transaction references where available.
- Prevention of normal stock-out transactions that would reduce stock below zero.

### Dashboard and reporting

- Dashboard indicators for active products, stock value and stock levels.
- Low-stock and out-of-stock visibility.
- Stock movement reports over selected date ranges.
- PDF and Excel exports.

### Accounts and permissions

The application provides four user roles:

| Function | Admin | Manager | Operator | Viewer |
|---|:---:|:---:|:---:|:---:|
| Dashboard | Yes | Yes | Yes | Yes |
| Products | Yes | Yes | Yes | Read-only |
| Categories, units, locations | Yes | Yes | No | No |
| Suppliers and customers | Yes | Yes | No | No |
| Purchases, sales and adjustments | Yes | Yes | Yes | No |
| Purchase orders | Yes | Yes | Yes | No |
| Damaged goods | Yes | Yes | Yes | No |
| Stock ledger | Yes | Yes | Yes | No |
| Reports | Yes | Yes | Yes | No |
| User management | Yes | No | No | No |
| Audit log | Yes | No | No | No |
| Application settings | Yes | No | No | No |

Additional controls:

- Viewer access is limited to Dashboard and read-only Products.
- Operators cannot override saved selling prices during sales.
- Damaged-goods deletion is restricted to administrators and recorded in the Audit Log.
- Passwords are hashed using PBKDF2-SHA256 with per-user random salts.
- Authorization is enforced in application services and the user interface where applicable.

### Local data and backups

- Local SQLite database.
- Database location selected during first-run setup.
- Configuration and data are stored separately from the program installation.
- Automatic daily backups with configurable retention.
- Manual backup and restore with database integrity checking.
- Existing databases are upgraded through Alembic migrations.
- Uninstallation preserves user data and backups.

### Windows installation

The application is packaged using PyInstaller and distributed through an Inno Setup installer.

The standard installation is per-user and does not normally require administrator privileges. The established installation identity and directory are retained to support in-place upgrades.

---

## Technology Stack

| Component | Technology |
|---|---|
| Programming language | Python 3.11+ |
| Desktop interface | PySide6 |
| Database | SQLite |
| ORM | SQLAlchemy |
| Database migrations | Alembic |
| PDF reports | ReportLab |
| Spreadsheet exports | openpyxl |
| Application packaging | PyInstaller |
| Windows installer | Inno Setup |
| Automated tests | pytest |

---

## Installation

The Windows setup executable is distributed separately from this source repository unless a release asset is published.

1. Obtain the Kaliwabo Inventory Windows installer from the project distributor.
2. Run the installer.
3. Complete the installation.
4. Launch Kaliwabo Inventory.
5. On first launch, choose the database location and create the initial administrator account.
6. Sign in and configure the application.

The application is designed for local operation. Normal inventory operations do not require a cloud account.

---

## Development Setup

### Requirements

- Windows
- Python 3.11 or newer
- Git

### Clone this repository

```powershell
git clone https://github.com/Clark-kn/offline_inventory_project.git
cd offline_inventory_project
git checkout we-rich-release-2026-11-12
```

### Create a virtual environment

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

### Install dependencies

```powershell
python -m pip install -r requirements.txt
```

### Run the application

```powershell
python main.py
```

Alternatively, use `run_app.bat` after installing the dependencies.

---

## Automated Testing

Run the complete test suite:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

The suite covers authentication, authorization, master data, purchases, sales, stock movements, damaged goods, purchase orders, reports, audit logging, migrations, backup and restore, application paths, timezone handling and application hardening.

**Release validation:** The latest recorded full regression run for the Kaliwabo 1.0.0 release candidate completed with **267 tests passing**.

This is a recorded validation result, not a guarantee that every future change will pass. Run the suite again after modifying the code.

---

## Building the Windows Application

Build the PyInstaller application folder:

```powershell
.\.venv\Scripts\python.exe -m PyInstaller inventory_manager.spec --noconfirm
```

Expected output:

```text
dist\InventoryManager\InventoryManager.exe
```

The build produces an application folder with supporting files; it is not a standalone one-file executable.

### Building the installer

Install Inno Setup 7 and compile the installer using its command-line compiler:

```powershell
ISCC.exe installer.iss
```

If `ISCC.exe` is not available on your PATH, run it using its full installation path. For example:

```powershell
& "C:\Program Files (x86)\Inno Setup 7\ISCC.exe" installer.iss
```

The installer output directory and filename are configured in `installer.iss`.

---

## Project Structure

```text
app/
|-- backup/         Backup-related functionality
|-- config/         Application configuration and data paths
|-- data/           Database models, sessions and migrations
|-- domain/         Domain logic
|-- reports/        Report generation and export helpers
|-- security/       Permissions and authorization helpers
|-- services/       Business logic and application services
|-- setup/          Application installation support
|-- ui/             PySide6 windows, dialogs and tabs
|-- utils/          Shared utilities
`-- viewmodels/     UI view models

tests/              Automated test suite
resources/          Application resources and stylesheets
main.py             Application entry point
alembic.ini         Alembic configuration
inventory_manager.spec
installer.iss       Inno Setup installer definition
requirements.txt    Python dependencies
run_app.bat         Development launch helper
```

---

## Scope and Security Notes

- Designed for local use on a Windows computer.
- Not a multi-computer synchronized or cloud-hosted inventory platform.
- Application permissions do not replace Windows account security.
- Backups should periodically be copied to a separate safe location.
- A backup stored on the same physical drive does not protect against drive failure.
- The software is provided under the terms of its MIT licence and without warranty.

---

## Licence

This project retains the original **MIT License** and its copyright notice.

See [LICENSE](LICENSE) for the complete licence text.

The original author's attribution and licence terms must be preserved when redistributing the project or substantial portions of it.
