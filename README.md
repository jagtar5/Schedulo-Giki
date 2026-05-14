# Schedulo - Automated Timetable Scheduling System

![Python](https://img.shields.io/badge/Python-3.8+-blue.svg)
![Flask](https://img.shields.io/badge/Flask-3.1+-green.svg)


**Schedulo** is an intelligent, automated timetable scheduling system designed for educational institutions. Built for GIK Institute's Faculty of Computer Science & Engineering, it generates conflict-free weekly timetables while optimizing for multiple soft constraints like minimizing student gaps and distributing workload evenly.

## 🎯 Features

- **Automated Timetable Generation**: Intelligent algorithm generates conflict-free schedules
- **CRUD Operations**: Full database management for all entities (Teachers, Courses, Rooms, Time Slots, etc.)
- **Lab Course Management**: Specialized handling for lab courses with faculty-specific room constraints
- **Real-time Conflict Detection**: Validates schedules against hard constraints
- **Visual Timetable Display**: Interactive web interface with grid-based timetable visualization
- **Demo Data Support**: Pre-configured sample dataset for quick testing
- **PDF Export**: Generate and export timetables as PDF reports
- **Responsive Design**: Bootstrap 5-based dark theme UI

## 📋 Prerequisites

Before you begin, ensure you have the following installed:

- **Python 3.8 or higher**: [Download Python](https://www.python.org/downloads/)
- **pip**: Usually included with Python
- **Git**: [Download Git](https://git-scm.com/)
- **Visual C++ Build Tools** (Windows only): Required for some dependencies like `pyodbc`

### Check Your Installation

```bash
python --version
pip --version
```

## ⚙️ Installation & Configuration

### Step 1: Clone or Download the Repository

```bash
# If using Git
git clone https://github.com/jagtar5/Schedulo-Giki
cd Project

# Or if you have a ZIP file, extract it and navigate to the folder
cd Project
```

### Step 2: Create a Virtual Environment

Creating a virtual environment isolates your project dependencies from your system Python installation.

**On Windows (PowerShell or CMD):**
```bash
python -m venv venv
venv\Scripts\activate
```

**On macOS/Linux:**
```bash
python3 -m venv venv
source venv/bin/activate
```

After activation, your terminal prompt will show `(venv)` at the beginning.

### Step 3: Install Dependencies

Ensure your virtual environment is activated, then install all required packages:

```bash
pip install -r requirements.txt
```

The main dependencies include:
- **Flask** (3.1.3): Web framework
- **Flask-SQLAlchemy** (3.1.1): Database ORM
- **SQLAlchemy** (2.0.49): SQL toolkit
- **WeasyPrint** (68.1): PDF generation
- **Jinja2** (3.1.6): Template engine

### Step 4: Configure the Application

The application configuration is handled in `schedulo/config.py`. Default settings are:

```python
SECRET_KEY = "gik-timetable-secret-key-2026"
SQLALCHEMY_DATABASE_URI = "sqlite:///timetable.db"
```

**To use a custom SECRET_KEY**, set an environment variable:

**On Windows (PowerShell):**
```powershell
$env:SECRET_KEY = "your-secret-key-here"
```

**On Windows (CMD):**
```cmd
set SECRET_KEY=your-secret-key-here
```

**On macOS/Linux:**
```bash
export SECRET_KEY="your-secret-key-here"
```

### Step 5: Initialize the Database

The database is automatically created when you first run the application. To pre-populate it with demo data:

1. Run the application (see next step)
2. Navigate to the home page
3. Click the **"Load Demo Data"** button
4. The system will seed the database with pre-configured courses, teachers, rooms, and time slots

## 🚀 Running the Application

### Start the Flask Development Server

Ensure your virtual environment is activated, then:

**On Windows:**
```bash
cd schedulo
python app.py
```

**On macOS/Linux:**
```bash
cd schedulo
python3 app.py
```

You should see output similar to:
```
 * Running on http://127.0.0.1:5000
 * Debug mode: on
```

### Access the Application

Open your web browser and navigate to:
```
http://localhost:5000
```

## 📁 Project Structure

```
Project/
├── venv/                        # Virtual environment (created during setup)
└── schedulo/                    # Main application folder
    ├── app.py                   # Flask app factory & entry point
    ├── config.py                # Configuration settings
    ├── models.py                # SQLAlchemy database models
    ├── routes.py                # Flask routes & CRUD endpoints
    ├── demo_data.py             # Demo data loading script
    ├── formatted_data.py        # Pre-configured dataset
    ├── analyze.py               # Dataset validation & feasibility checks
    ├── master_algoritham.py     # Core scheduling algorithm
    ├── _inspect.py              # Debugging utilities
    ├── weekly_pdf_builder.py    # PDF generation module
    ├── timetable.db             # SQLite database (created at runtime)
    ├── static/
    │   ├── style.css            # Custom CSS styles
    │   ├── script.js            # JavaScript utilities
    │   └── css/
    │       └── timetable_pdf.css # PDF styling
    └── templates/
        ├── base.html            # Base template with navbar
        ├── index.html           # Landing page
        ├── manage_teachers.html # Teacher management
        ├── manage_courses.html  # Course management
        ├── manage_rooms.html    # Room management
        ├── manage_groups.html   # Student group management
        ├── manage_timeslots.html # Time slot management
        ├── manage_offerings.html # Course offering management
        ├── manage_lab_policies.html # Lab course policies
        └── timetable.html       # Timetable visualization
```

## 📊 Database Models

The application uses SQLite with the following main entities:

| Model | Description |
|-------|-------------|
| **Teacher** | Faculty members with department & workload constraints |
| **Course** | Academic courses (Theory/Lab) with session requirements |
| **Room** | Lecture halls and lab spaces |
| **StudentGroup** | Cohorts of students (e.g., Batch 33 - Section A) |
| **TimeSlot** | Weekly time slots (Mon-Fri, 8:00-17:20) |
| **CourseOffering** | Class instance (Course + Teacher + StudentGroup) |
| **LabCoursePolicy** | Lab course to faculty mapping for constraint validation |
| **Schedule** | Generated timetable assignments (output) |

## 🎓 Usage Guide

### 1. Load Demo Data
- Click **"Load Demo Data"** on the home page to populate the database with sample data
- This creates sample teachers, courses, rooms, and a complete timetable

### 2. Manage Entities (Optional)
Navigate to the management pages to view or modify:
- Teachers
- Courses
- Rooms
- Student Groups
- Time Slots
- Course Offerings
- Lab Policies

### 3. Generate Timetable
- Click **"Generate Timetable"** to run the scheduling algorithm
- The system will:
  - Validate all constraints
  - Optimize for soft constraints (student gaps, workload distribution)
  - Generate a conflict-free schedule

### 4. View Timetable
- Browse the generated timetable by weekday
- Filter by Group, Teacher, or Course
- Each cell shows: Course Code, Teacher, Room, Student Group

### 5. Export as PDF (Optional)
- Click **"Export to PDF"** to download the timetable as a formatted PDF

## 🔧 Troubleshooting

### Issue: Virtual Environment Not Activating
**Solution**: Ensure you're in the correct directory and run the activate script from the root `Project` folder:
```bash
cd Project
venv\Scripts\activate  # Windows
source venv/bin/activate  # macOS/Linux
```

### Issue: Module Not Found Error
**Solution**: Reinstall dependencies:
```bash
pip install --upgrade -r requirements.txt
```

### Issue: Database Locked Error
**Solution**: Delete the `timetable.db` file and restart the application:
```bash
rm schedulo/timetable.db  # macOS/Linux
del schedulo\timetable.db  # Windows
python schedulo/app.py
```

### Issue: Port 5000 Already in Use
**Solution**: Change the port in `schedulo/app.py`:
```python
if __name__ == '__main__':
    app.run(debug=True, port=5001)  # Use port 5001 instead
```

## 📝 Configuration Guide

### Custom Database
To use a different database (e.g., MySQL, PostgreSQL), modify `schedulo/config.py`:

```python
# PostgreSQL example
SQLALCHEMY_DATABASE_URI = "postgresql://user:password@localhost/schedulo_db"
```

### Debug Mode
To disable debug mode in production, modify `schedulo/app.py`:
```python
app.run(debug=False)
```

### Logging
Enable logging for debugging by adding to `schedulo/app.py`:
```python
import logging
logging.basicConfig(level=logging.DEBUG)
```

## 🎯 Key Constraints Implemented

### Hard Constraints (Must Be Satisfied)
- ✅ Teacher availability (no overlapping classes)
- ✅ Room availability (no double-booking)
- ✅ Student group availability (no schedule conflicts)
- ✅ Session fulfillment (all required slots scheduled)

### Soft Constraints (Optimized)
- 📊 Minimize student gaps between classes
- 🔄 Limit consecutive lectures per teacher
- 🏢 Match room capacity to group size
- ⚖️ Distribute workload across the week
- 🎓 Prevent elective conflicts

## 🛠️ Development

### Adding New Features

1. **Add a new entity**: Update `schedulo/models.py`
2. **Add CRUD routes**: Update `schedulo/routes.py`
3. **Create management UI**: Add template in `schedulo/templates/`
4. **Update navigation**: Modify `schedulo/templates/base.html`

### Running Tests

Currently, the project uses manual testing. For automated testing:
```bash
pip install pytest pytest-flask
pytest tests/
```


## 🤝 Contributing

Contributions are welcome! To contribute:

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/YourFeature`)
3. Commit your changes (`git commit -m 'Add YourFeature'`)
4. Push to the branch (`git push origin feature/YourFeature`)
5. Open a Pull Request

Please ensure:
- Code follows PEP 8 style guidelines
- Changes are well-documented
- Database migrations are included if needed


## ℹ️ Course Information

- **Course**: CS378 - Design and Analysis of Algorithms
- **Institution**: GIK Institute of Engineering Sciences and Technology
- **Target**: Faculty of Computer Science & Engineering (FCSE)
- **Year**: 2026



**Happy Scheduling! 📚✨**
