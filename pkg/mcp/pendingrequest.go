package mcp

import "sync"

type PendingRequests struct {
	lock sync.Mutex
	ids  map[any]chan Message
}

func (p *PendingRequests) WaitFor(id any) chan Message {
	p.lock.Lock()
	defer p.lock.Unlock()
	if p.ids == nil {
		p.ids = make(map[any]chan Message)
	}
	ch := make(chan Message, 1)
	p.ids[id] = ch
	return ch
}

func (p *PendingRequests) Notify(msg Message) bool {
	p.lock.Lock()
	defer p.lock.Unlock()

	ch, ok := p.ids[msg.ID]
	if ok {
		select {
		case ch <- msg:
			return true
			// don't let it block, we are holding the lock
		default:
		}
		delete(p.ids, msg.ID)
	}
	return false
}

func (p *PendingRequests) Done(id any) {
	p.lock.Lock()
	defer p.lock.Unlock()

	delete(p.ids, id)
}

func (p *PendingRequests) Close() {
	p.lock.Lock()
	defer p.lock.Unlock()

	for _, ch := range p.ids {
		close(ch)
	}
	p.ids = nil
}
