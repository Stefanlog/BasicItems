
import json
import re

def parse_weapons(file_path):
    weapons = []
    with open(file_path, 'r') as f:
        lines = f.readlines()

    current_weapon = None
    for line in lines:
        line = line.strip()
        if not line or line.startswith('#'):
            continue

        if line.startswith('newweapon'):
            if current_weapon:
                weapons.append(current_weapon)
            
            match = re.search(r'newweapon\s+"([^"]+)"', line)
            if match:
                weapon_name = match.group(1)
                current_weapon = {
                    "id": weapon_name.lower().replace(" ", "_"),
                    "name": weapon_name,
                    "description": "",
                    "icon": "",
                    "stackable": False,
                    "weight": 1.0,
                    "value": 50,
                    "type": "weapon",
                    "stats": {
                        "magic": True
                    }
                }
        elif current_weapon:
            parts = line.split()
            if len(parts) >= 2:
                key = parts[0]
                value = parts[1]

                if key == 'dmg':
                    current_weapon['stats']['damage_min'] = int(value)
                    current_weapon['stats']['damage_max'] = int(value)
                elif key == 'dmgtype':
                    # Need to map this value
                    current_weapon['stats']['damage_type'] = value
                elif key == 'range':
                    current_weapon['stats']['range'] = int(value)
                elif key == 'aoe':
                    # Need to map this
                    current_weapon['stats']['aoe'] = value
                elif key == 'mundane':
                    current_weapon['stats']['magic'] = False

    if current_weapon:
        weapons.append(current_weapon)

    return weapons

if __name__ == "__main__":
    weapon_data = parse_weapons('Weapon Data v5.33.txt')
    print(json.dumps(weapon_data, indent=2))
