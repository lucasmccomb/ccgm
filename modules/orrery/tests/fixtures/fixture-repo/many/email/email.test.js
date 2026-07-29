const m = require('./index')
if (m.feature !== 'email') throw new Error('fixture self-check')
