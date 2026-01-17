"""
Locations API Routes
"""
from flask import Blueprint, request, jsonify
from flask_login import login_required
from cms.models import db

locations_bp = Blueprint('locations', __name__)

class Location(db.Model):
    __tablename__ = 'locations'
    id = db.Column(db.String(36), primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    address = db.Column(db.String(500))
    icon = db.Column(db.String(50))
    color = db.Column(db.String(20))
    created_at = db.Column(db.DateTime, default=db.func.now())

    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'address': self.address,
            'icon': self.icon,
            'color': self.color
        }

@locations_bp.route('', methods=['POST'])
@login_required
def create_location():
    import uuid
    data = request.get_json()
    
    location = Location(
        id=str(uuid.uuid4()),
        name=data.get('name'),
        address=data.get('address'),
        icon=data.get('icon'),
        color=data.get('color')
    )
    
    db.session.add(location)
    db.session.commit()
    
    return jsonify(location.to_dict()), 201

@locations_bp.route('', methods=['GET'])
@login_required
def list_locations():
    locations = Location.query.all()
    return jsonify([loc.to_dict() for loc in locations])
