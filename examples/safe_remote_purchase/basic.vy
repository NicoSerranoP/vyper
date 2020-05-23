value: public(uint256)
seller: public(address)
buyer: public(address)
unlocked: public(bool)

@public
@payable
def __init__():
    assert (msg.value % 2) == 0
    self.value = msg.value / 2
    self.seller = msg.sender
    #self.unlocked = True
    unlock [purchase, abort]

@public
def abort():
    #assert self.unlocked
    assert msg.sender == self.seller
    selfdestruct(self.seller)
unlock []

@public
@payable
def purchase():
    #assert self.unlocked
    assert msg.value == (2 * self.value)
    self.buyer = msg.sender
    #self.unlocked = False
    unlock []
