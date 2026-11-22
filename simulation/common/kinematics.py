"""
Turret FK/IK - CORRECT kinematic chain.

Physical mounting (re-aligned by user 2026-11-19):
  Y (tilt) joint = A, bolted to the BASE, 2.5 cm above floor
  X (pan)  joint = B, mounted ON the tilt bracket
  Laser        = mounted ON the pan bracket

Measured offsets (new alignment):
  B = A + (-2.5 right [2.5 west], 0 forward, 2.5 up) cm   (at tilt = 0)
  L = B + (+2.5 right [2.5 east], 0 forward, -1.5 up) cm  (at pan = 0, tilt = 0)
  => laser tip rel. A = (0, 0, 1.0) cm, i.e. 1 cm above the tilt base.

Frame: e = right, n = forward, u = up. Origin = A (tilt base).

TRANSFORM ORDER: TILT FIRST, THEN PAN.
The pan axis itself tilts with the bracket, so beam azimuth depends on tilt.
This is the opposite of the usual pan-tilt chain and is why the naive
"az = pan, el = tilt" mapping is wrong for this turret.

Servo mapping (new centre X100 Y80):
  pan  = X - 100  (deg, + = right)
  tilt = 80 - Y   (deg, + = up)

Envelope: X 50..150 (pan +/-50), Y 40..140 (tilt +40..-60).
Y below 40 is forbidden - the laser hides in the mount.

Wall distance D is a parameter - no fixed wall assumption.
"""

import math

# --- measured geometry, cm (new alignment 2026-11-19) ---
E_B, N_B, U_B = -2.5, 0.0, 2.5    # pan axis B = 2.5 west + 2.5 up from tilt base A
E_L, N_L, U_L = 2.5, 0.0, -1.5    # laser = 2.5 east + 1.5 down from pan axis B

CENTRE_X = 100.0
CENTRE_Y = 80.0
X_MIN, X_MAX = 50.0, 150.0
Y_MIN, Y_MAX = 40.0, 140.0


def servo_to_angles(x, y):
    """Servo PWM angles -> physical (pan, tilt) degrees."""
    return x - CENTRE_X, CENTRE_Y - y


def angles_to_servo(pan, tilt):
    """Physical (pan, tilt) degrees -> servo PWM angles."""
    return CENTRE_X + pan, CENTRE_Y - tilt


def clamp_servo(x, y):
    return (max(X_MIN, min(X_MAX, x)),
            max(Y_MIN, min(Y_MAX, y)))


def _rot_e(p, deg):
    """Rotate point about the world east axis; +deg = nose up."""
    c, s = math.cos(math.radians(deg)), math.sin(math.radians(deg))
    e, n, u = p
    return (e, n * c - u * s, n * s + u * c)


def _rot_local_u(local, deg):
    """Rotate local (e,n,u) coords about the LOCAL up axis; +deg = right."""
    e, n, u = local
    c, s = math.cos(math.radians(deg)), math.sin(math.radians(deg))
    return (e * c + n * s, -e * s + n * c, u)


def laser_pose(x, y):
    """Return (laser position rel. tilt base A, beam unit vector).

    Tilt first (about world east through A), then pan about the pan axis,
    which has been carried/tilted with the bracket.
    """
    pan, tilt = servo_to_angles(x, y)
    cp, sp = math.cos(math.radians(pan)), math.sin(math.radians(pan))
    ct, st = math.cos(math.radians(tilt)), math.sin(math.radians(tilt))

    # tilted local basis
    e_ax = (1.0, 0.0, 0.0)
    n_ax = (0.0, ct, st)
    u_ax = (0.0, -st, ct)

    # pan axis B sits on the tilt carrier -> does not move when pan rotates
    B = _rot_e((E_B, N_B, U_B), tilt)

    # laser offset: pan about local up, then map local -> world tilted basis
    local = _rot_local_u((E_L, N_L, U_L), pan)
    r = tuple(local[0] * e_ax[i] + local[1] * n_ax[i] + local[2] * u_ax[i]
              for i in range(3))
    pos = (B[0] + r[0], B[1] + r[1], B[2] + r[2])

    # beam = local forward, tilted then panned
    direction = (sp, cp * ct, cp * st)
    return pos, direction


def beam_angles(x, y):
    """Servo angles -> beam (azimuth, elevation) in degrees.

    With the tilt-first chain these are NOT simply (x-100, 80-y).
    """
    _, d = laser_pose(x, y)
    return (math.degrees(math.atan2(d[0], d[1])),
            math.degrees(math.atan2(d[2], math.hypot(d[0], d[1]))))


def _ik_direction(az, el):
    """Exact beam (az, el) -> physical (pan, tilt). No clamping."""
    ce, se = math.cos(math.radians(el)), math.sin(math.radians(el))
    ca, sa = math.cos(math.radians(az)), math.sin(math.radians(az))

    # d = (sin(pan), cos(pan)cos(tilt), cos(pan)sin(tilt))
    s_pan = ce * sa
    c_pan = math.sqrt(max(0.0, ce * ce * ca * ca + se * se))
    pan = math.degrees(math.atan2(s_pan, c_pan))
    tilt = math.degrees(math.atan2(se, ce * ca))
    return pan, tilt


def aim_at_direction(az, elevation):
    """Beam (azimuth, elevation) degrees -> safe servo angles (X, Y).

    az      : + = right, clamped to +/-50 (X 50..150)
    elevation: + = up,   clamped to -60..+40 (Y 140..40)
    """
    az = max(-50.0, min(50.0, az))
    elevation = max(-60.0, min(40.0, elevation))
    pan, tilt = _ik_direction(az, elevation)
    return clamp_servo(*angles_to_servo(pan, tilt))


def forward(x, y, distance):
    """Servo angles + wall distance (cm, from tilt base A) -> wall (east, up)."""
    pos, d = laser_pose(x, y)
    t = (distance - pos[1]) / d[1]
    return pos[0] + t * d[0], pos[2] + t * d[2]


def inverse(e_wall, u_wall, distance, iterations=30):
    """Desired wall dot (cm) at distance -> safe servo angles (X, Y)."""
    x, y = aim_at_direction(math.degrees(math.atan2(e_wall, distance)),
                            math.degrees(math.atan2(u_wall, distance)))
    for _ in range(iterations):
        pos, _ = laser_pose(x, y)
        de = e_wall - pos[0]
        dn = distance - pos[1]
        du = u_wall - pos[2]
        az = math.degrees(math.atan2(de, dn))
        el = math.degrees(math.atan2(du, math.hypot(de, dn)))
        nx, ny = aim_at_direction(az, el)
        if abs(nx - x) < 1e-6 and abs(ny - y) < 1e-6:
            x, y = nx, ny
            break
        x, y = nx, ny
    return x, y


if __name__ == "__main__":
    print("laser rel. tilt base A:",
          (E_B + E_L, N_B + N_L, U_B + U_L))
    print("\nbeam coupling (tilt-first chain):")
    for x, y in ((100, 80), (130, 60), (150, 40), (50, 140)):
        az, el = beam_angles(x, y)
        print("  X%3d Y%3d -> az %+7.2f  el %+7.2f  (naive %+d / %+d)"
              % (x, y, az, el, x - CENTRE_X, CENTRE_Y - y))

    print("\nIK round-trip:")
    for az, el in ((0, 0), (40, 25), (-40, -35), (50, 40), (-50, -60)):
        x, y = aim_at_direction(az, el)
        a2, e2 = beam_angles(x, y)
        print("  want %+6.1f/%+6.1f -> X%6.2f Y%6.2f -> got %+6.2f/%+6.2f"
              % (az, el, x, y, a2, e2))

    print("\nwall round-trip at 200cm:")
    for e, u in ((0, 0), (50, 30), (-50, -30)):
        x, y = inverse(e, u, 200.0)
        fe, fu = forward(x, y, 200.0)
        print("  want (%+6.1f,%+6.1f) -> X%6.2f Y%6.2f -> got (%+6.2f,%+6.2f)"
              % (e, u, x, y, fe, fu))
