value: public(uint256) #Value of the item
seller: public(address)
buyer: public(address)
unlocked: public(bool)
ended: public(bool)

@public
@payable
def __init__():
    assert (msg.value % 2) == 0
    self.value = msg.value / 2  # The seller initializes the contract by posting a safety deposit of 2*value of the item up for sale.
    self.seller = msg.sender
    self.unlocked = True
    unlock ['abort','purchase']

@public
def abort():
    assert self.unlocked #Is the contract still refundable?
    assert msg.sender == self.seller # Only the seller can refund his deposit before any buyer purchases the item.
    selfdestruct(self.seller) # Refunds the seller and deletes the contract.
    unlock []

@public
@payable
def purchase():
    assert self.unlocked # Is the contract still open (is the item still up for sale)?
    assert msg.value == (2 * self.value) # Is the deposit the correct value?
    self.buyer = msg.sender
    self.unlocked = False
    unlock ['received']

@public
def received():
    assert not self.unlocked # Is the item already purchased and pending onfirmation from the buyer?
    assert msg.sender == self.buyer
    assert not self.ended
    self.ended = True
    send(self.buyer, self.value) # Return the buyer's deposit (=value) to the buyer.
    selfdestruct(self.seller) # Return the seller's deposit (=2*value) and the
    unlock []                  # purchase price (=value) to the seller.
