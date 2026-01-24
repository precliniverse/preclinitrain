# Preclinitrain

This web application is designed for managing training activities, skills, and user competencies within an organization. It features user authentication, role-based access, and a comprehensive interface for tracking users, teams, species, skills, training paths, training sessions, and various training-related events (requests, external trainings, skill practices, competencies). The application supports internationalization (French and English) and integrates with a MariaDB or sqlite database.

## Features

*   User Authentication and Role-Based Access
*   Management of Users, Teams, Species, Skills
*   Training Path and Session Management
*   Tracking of Training Requests, External Trainings, Skill Practices, and Competencies
*   Internationalization (English and French)
*   RESTful API

## Technologies Used

*   **Backend:** Python, Flask
*   **Database:** MariaDB (via Docker), SQLite
*   **ORM:** SQLAlchemy, Flask-Migrate
*   **Authentication:** Flask-Login
*   **Internationalization:** Flask-Babel
*   **Email:** Flask-Mail
*   **API:** Flask-RESTX
*   **Deployment:** Docker, Docker Compose, Gunicorn
*   **Testing:** Pytest
*   **Data Seeding:** Faker

## PrecliniTrain Manager CLI

The application includes a powerful management CLI (`manage.py`) that handles setup, deployment, and maintenance across Windows and Linux.

### Interactive Menu
Simply run the script without arguments to access the interactive menu:
```bash
python manage.py
```

### Common Commands
*   `python manage.py setup`: Run the interactive configuration wizard (sets up `.env`).
*   `python manage.py deploy`: One-command deployment (handles Docker or Native mode).
*   `python manage.py start`: Start the application services.
*   `python manage.py stop`: Stop the application services.
*   `python manage.py restart`: Restart the application.
*   `python manage.py status`: View current application and system health status.
*   `python manage.py logs`: View live application logs.
*   `python manage.py create-admin`: Create a new administrator user.
*   `python manage.py link-ecosystem`: Configure integration with Precliniverse.

## Getting Started

### 1. Prerequisites
*   **Docker Mode (Recommended):** Docker and Docker Compose.
*   **Native Mode:** Python 3.9+ and a database (MariaDB/MySQL or SQLite).

### 2. Initial Setup
Run the setup wizard to configure your environment:
```bash
python manage.py setup
```
Follow the prompts to configure deployment mode, ports, database credentials, and admin user. This will create your `.env` file.

### 3. Deployment
Deploy the application based on your setup configuration:
```bash
python manage.py deploy
```

### 4. Access the Application
Once deployed, start the application (if not already running) and access it at the configured port:
```bash
python manage.py start
```
By default, the application is accessible at `http://localhost:5001`.

## Advanced Deployment Notes

### OS Compatibility
The `manage.py` CLI automatically handles OS-specific requirements:
*   **Windows:** Uses `waitress` as the production WSGI server.
*   **Linux/Unix:** Uses `gunicorn` for high-performance serving.

### Docker Networking
In Docker mode, the application uses the `lab_ecosystem` external network to facilitate communication with other services like Precliniverse. The CLI will attempt to create this network if it doesn't exist.

## Testing

To execute the test suite:
```bash
pytest
```

## License

The code is provided under the GNU Affero General Public License v3.0 (AGPLv3), allowing free use, modification, and distribution for non-commercial, academic, and community contribution purposes.

For any commercial use (e.g., integration into proprietary products, paid SaaS offerings without sharing AGPLv3-compliant modifications), a separate commercial license must be negotiated. Please create an issue for inquiries.
