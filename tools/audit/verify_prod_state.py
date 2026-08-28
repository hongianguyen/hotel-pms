# Read-only audit of prod reception access + admin-rights exposure.
# Ends in rollback; changes nothing.

reception = env.ref('hotel_core.group_hotel_reception')
hotel_admin = env.ref('hotel_core.group_hotel_admin')
sysadmin = env.ref('base.group_system')

logins = ['fb@laktentedcamp.com', 'sales@laktentedcamp.com',
          'res@laktentedcamp.com', 'om@laktentedcamp.com', 'Anh', 'admin']

print('=' * 78)
print('%-26s %-10s %-6s %-11s %-9s %s'
      % ('LOGIN', 'RECEPTION', 'ADMIN', 'group_system', 'hotel.room', 'GANTT'))
print('=' * 78)

for login in logins:
    u = env['res.users'].search([('login', '=', login)])
    if not u:
        print('%-26s NO SUCH USER' % login)
        continue
    try:
        env['hotel.room'].with_user(u.id).check_access('read')
        room = 'READ-OK'
    except Exception:
        room = 'DENIED'
    try:
        env['hotel.dashboard'].with_user(u.id).get_gantt_data()
        gantt = 'OK'
    except Exception as e:
        gantt = 'FAIL:' + type(e).__name__ + ':' + str(e)[:60]
    print('%-26s %-10s %-6s %-11s %-9s %s'
          % (login,
             reception in u.group_ids,
             hotel_admin in u.group_ids,
             sysadmin in u.group_ids,
             room,
             gantt))

# Anyone else holding sysadmin that the list above misses?
others = env['res.users'].search([('group_ids', 'in', sysadmin.id),
                                  ('login', 'not in', logins)])
print('\n--- other users with base.group_system ---')
for u in others:
    print('   uid=%-4s %-30s active=%s share=%s'
          % (u.id, u.login, u.active, u.share))
if not others:
    print('   (none)')

# Does the unlink grant that was applied yesterday still hold?
acl = env['ir.model.access'].search([
    ('model_id.model', '=', 'hotel.reservation'),
    ('group_id', '=', reception.id)])
print('\n--- hotel.reservation ACL for Hotel Reception ---')
for a in acl:
    print('   %-40s r=%s w=%s c=%s unlink=%s'
          % (a.name, a.perm_read, a.perm_write, a.perm_create, a.perm_unlink))

env.cr.rollback()
