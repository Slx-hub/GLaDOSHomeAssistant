alias rhstart='docker start gladosrhasspy'
alias rhstop='docker stop gladosrhasspy'
alias rhrestart='docker restart gladosrhasspy'
alias rhlogs='docker logs -f gladosrhasspy'
alias glstart='sudo sytemctl start glados.service'
alias glrestart='sudo systemctl restart glados.service'
alias glstop='sudo systemctl stop glados.service'
alias glados='journalctl -u glados.service -f'
alias brstart='sudo systemctl start http_bridge.service'
alias brrestart='sudo systemctl restart http_bridge.service'
alias brstop='sudo systemctl stop http_bridge.service'
alias bridge='journalctl -u http_bridge.service -f'

glcmd() {
    curl "http://localhost:5123/intent/ChangeSocketState?source=$1&state=$2"
}