const m = require('./index')
if (m.feature !== 'audit-log') throw new Error('fixture self-check')
