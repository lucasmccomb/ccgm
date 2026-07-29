const m = require('./index')
if (m.feature !== 'analytics') throw new Error('fixture self-check')
