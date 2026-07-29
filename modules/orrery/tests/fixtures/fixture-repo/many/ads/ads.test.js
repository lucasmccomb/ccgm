const m = require('./index')
if (m.feature !== 'ads') throw new Error('fixture self-check')
