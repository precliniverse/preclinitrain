import click
from flask.cli import with_appcontext
from app import db
from app.models import (
    User, Team, Species, Skill, Complexity, 
    InitialRegulatoryTraining, InitialRegulatoryTrainingLevel,
    ContinuousTrainingEvent, ContinuousTrainingEventStatus, ContinuousTrainingType, 
    TrainingRequest, TrainingRequestStatus,
    Role, TrainingSession, Competency, ExternalTraining, ExternalTrainingStatus
)
from datetime import datetime, timedelta, timezone
from werkzeug.security import generate_password_hash
import random

def get_or_create(model, **kwargs):
    instance = model.query.filter_by(**kwargs).first()
    if instance:
        return instance
    instance = model(**kwargs)
    db.session.add(instance)
    db.session.commit()
    return instance

def create_demo_data_command():
    """Generates demo data for preclinical scientists (Mouse & Rat study)."""
    print("Generating demo data...")
    
    # 1. Create Species
    mouse = get_or_create(Species, name='Mouse')
    rat = get_or_create(Species, name='Rat')
    print(f"Species created: {mouse.name}, {rat.name}")

    # 2. Create Teams
    oncology = get_or_create(Team, name='Oncology Team')
    neuro = get_or_create(Team, name='Neuroscience Team')
    print(f"Teams created: {oncology.name}, {neuro.name}")

    # 3. Create Users
    # Admin
    admin = User.query.filter_by(email='admin_demo@preclini.com').first()
    if not admin:
        admin = User(
            full_name='Demo Admin',
            email='admin_demo@preclini.com',
            is_admin=True,
            is_approved=True,
            study_level='PhD'
        )
        admin.set_password('demo1234')
        db.session.add(admin)
        print("Created Admin: admin_demo@preclini.com")
    
    # Mouse Scientist (Alice)
    mouse_user = User.query.filter_by(email='scientist_mouse@preclini.com').first()
    if not mouse_user:
        mouse_user = User(
            full_name='Alice MouseHandler',
            email='scientist_mouse@preclini.com',
            is_admin=False,
            is_approved=True,
            study_level='Master'
        )
        mouse_user.set_password('demo1234')
        db.session.add(mouse_user)
        print("Created User: scientist_mouse@preclini.com")
    
    # Rat Scientist (Bob)
    rat_user = User.query.filter_by(email='scientist_rat@preclini.com').first()
    if not rat_user:
        rat_user = User(
            full_name='Bob RatWhisperer',
            email='scientist_rat@preclini.com',
            is_admin=False,
            is_approved=True,
            study_level='Bachelor'
        )
        rat_user.set_password('demo1234')
        db.session.add(rat_user)
        print("Created User: scientist_rat@preclini.com")

    db.session.commit()

    # Assign Teams
    if oncology not in mouse_user.teams:
        mouse_user.teams.append(oncology)
    if neuro not in rat_user.teams:
        rat_user.teams.append(neuro)
    
    # Assign Roles
    user_role = Role.query.filter_by(name='User').first()
    tutor_role = Role.query.filter_by(name='Tutor').first()
    
    for user in [mouse_user, rat_user]:
        if user_role and user_role not in user.roles:
            user.roles.append(user_role)

    # Make Admin a Tutor
    if tutor_role and tutor_role not in admin.roles:
        admin.roles.append(tutor_role)

    # Make Alice a Tutor (Peer Tutor example)
    if tutor_role and tutor_role not in mouse_user.roles:
        mouse_user.roles.append(tutor_role)
    
    db.session.commit()

    # 4. Create Skills
    skills_data = [
        # Mouse Skills
        {
            "name": "Mouse Restraint",
            "description": "Proper handling and restraint of mice.",
            "species": [mouse],
            "complexity": Complexity.SIMPLE,
            "validity": 12
        },
        {
            "name": "Mouse IP Injection",
            "description": "Intraperitoneal injection in mice.",
            "species": [mouse],
            "complexity": Complexity.MODERATE,
            "validity": 12
        },
        # Rat Skills
        {
            "name": "Rat Restraint",
            "description": "Proper handling and restraint of rats.",
            "species": [rat],
            "complexity": Complexity.SIMPLE,
            "validity": 24 # Longer validity
        },
        {
            "name": "Rat Oral Gavage",
            "description": "Oral gavage administration in rats.",
            "species": [rat],
            "complexity": Complexity.COMPLEX,
            "validity": 12
        }
    ]

    created_skills = {}
    for data in skills_data:
        skill = Skill.query.filter_by(name=data["name"]).first()
        if not skill:
            skill = Skill(
                name=data["name"],
                description=data["description"],
                complexity=data["complexity"],
                validity_period_months=data["validity"],
                reference_urls_text="https://example.com/sop/123"
            )
            for sp in data["species"]:
                skill.species.append(sp)
            db.session.add(skill)
            print(f"Created Skill: {skill.name}")
        created_skills[skill.name] = skill
    
    db.session.commit()

    # 5. Assign Tutored Skills
    # Admin tutors everything
    for skill in created_skills.values():
        if skill not in admin.tutored_skills:
            admin.tutored_skills.append(skill)
    
    # Alice tutors "Mouse Restraint"
    mouse_restraint = created_skills["Mouse Restraint"]
    if mouse_restraint not in mouse_user.tutored_skills:
        mouse_user.tutored_skills.append(mouse_restraint)

    db.session.commit()
    print("Assigned Tutored Skills")

    # 6. Training Session
    # Create a past session led by Admin for Mouse Skills
    session = TrainingSession.query.filter_by(title="Intro to Mouse Handling").first()
    if not session:
        session = TrainingSession(
            title="Intro to Mouse Handling",
            location="Room 101",
            start_time=datetime.now(timezone.utc) - timedelta(days=60),
            end_time=datetime.now(timezone.utc) - timedelta(days=60, hours=4),
            main_species=mouse,
            animal_count=10,
            status='Validated'
        )
        session.tutors.append(admin)
        # Alice attended
        session.attendees.append(mouse_user)
        # Skills covered
        session.skills_covered.append(mouse_restraint)
        session.skills_covered.append(created_skills["Mouse IP Injection"])
        
        db.session.add(session)
        print("Created Training Session: Intro to Mouse Handling")
        db.session.commit()

    # 7. Competencies and Outdated Skills
    # Alice: Valid "Mouse Restraint" (validated recently)
    comp_restraint = Competency.query.filter_by(user=mouse_user, skill=mouse_restraint).first()
    if not comp_restraint:
        comp_restraint = Competency(
            user=mouse_user,
            skill=mouse_restraint,
            level='Expert',
            evaluation_date=datetime.now(timezone.utc) - timedelta(days=30),
            evaluator=admin,
            training_session=session
        )
        db.session.add(comp_restraint)

    # Alice: OUTDATED "Mouse IP Injection"
    # Validity is 12 months. Evaluation was 14 months ago.
    skill_ip = created_skills["Mouse IP Injection"]
    comp_ip = Competency.query.filter_by(user=mouse_user, skill=skill_ip).first()
    if not comp_ip:
        comp_ip = Competency(
            user=mouse_user,
            skill=skill_ip,
            level='Intermediate',
            evaluation_date=datetime.now(timezone.utc) - timedelta(days=14 * 30), # 14 months ago approx
            evaluator=admin
        )
        db.session.add(comp_ip)
        print(f"Created OUTDATED Competency for Alice: {skill_ip.name} (Evaluated 14 months ago, Validity 12 months)")

    # Bob: Valid "Rat Restraint"
    skill_rat_restraint = created_skills["Rat Restraint"]
    comp_bob = Competency.query.filter_by(user=rat_user, skill=skill_rat_restraint).first()
    if not comp_bob:
        comp_bob = Competency(
            user=rat_user,
            skill=skill_rat_restraint,
            level='Novice',
            evaluation_date=datetime.now(timezone.utc) - timedelta(days=10),
            evaluator=admin # Admin validated
        )
        db.session.add(comp_bob)

    db.session.commit()

    # 8. Regulatory Training (Initial)
    if not mouse_user.initial_regulatory_trainings:
        reg_training = InitialRegulatoryTraining(
            user=mouse_user,
            level=InitialRegulatoryTrainingLevel.NIVEAU_2_EXPERIMENTATEUR,
            training_date=datetime.now(timezone.utc) - timedelta(days=700)
        )
        db.session.add(reg_training)

    if not rat_user.initial_regulatory_trainings:
        reg_training = InitialRegulatoryTraining(
            user=rat_user,
            level=InitialRegulatoryTrainingLevel.NIVEAU_1_CONCEPTEUR,
            training_date=datetime.now(timezone.utc) - timedelta(days=100)
        )
        db.session.add(reg_training)

    # 9. Continuous Training Event
    ethics_event = ContinuousTrainingEvent.query.filter_by(title="Animal Ethics Workshop 2025").first()
    if not ethics_event:
        ethics_event = ContinuousTrainingEvent(
            title="Animal Ethics Workshop 2025",
            description="Annual update on 3Rs and ethics.",
            training_type=ContinuousTrainingType.PRESENTIAL,
            location="Conference Room A",
            event_date=datetime.now(timezone.utc) - timedelta(days=30),
            duration_hours=7,
            creator=admin,
            status=ContinuousTrainingEventStatus.APPROVED 
        )
        db.session.add(ethics_event)

    db.session.commit()

    print("Demo data generation complete!")
