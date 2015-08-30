#!/bin/bash
# Daemonized loop below for use with volumed.sh
#----------------------------------------------------------------------------

while :
do
	# Here to prevent race conditions
	sleep 1

	# Add zones here, separate zone names with a space.  They are case
	# sensitive. Set volume limits in the order of the zones listed
	# below.  I.e. the first zone volume will apply to the first 
	# zone name in $sonosZONE

	sonosZONE=( Deck Spa )
	zoneVOLUME=( 50 50 )

	# Loop through the zones and check their volume.  Reset accordingly.
	ctr=0
	for i in "${sonosZONE[@]}"
	do
		# Get our Zone Specific Max Volume
		maxVOLUME="${zoneVOLUME[$ctr]}"

	        # Check the current time.  If it is after 11pm set the max volume to 20%
        	# If it is after midnight and before 7am, set it to 0.

	        curTIME=`date +%k%M`

	        if [ "$curTIME" -gt  2300 -a "$curTIME" -lt 2359 ]
        	then
                	maxVOLUME=20
	        fi

        	if [ "$curTIME" -gt 0 -a  "$curTIME" -lt 700 ]
	        then
        	        # Effectively mute it.
                	maxVOLUME=0
	        fi

		# If we've made it this far, we are checking now to see if the current volume is > maxVOLUME
		# as defined above.  If it is, reset the volume.

		# Set the zone to the input from $sonosZONE
		curl -s http://192.168.1.110:50101/data/rendererData?data=R::"$i"%20%28ZP%29 &>/dev/null 

		# Grab the relevant information about the zone so we can check the volume. 
		INFO=$(curl -s $(echo "http://192.168.1.110:50101/data/rendererAction?data=class" | sed 's/ //g'))

		# Strip it just down to the volume number, no other information.
		INFO=${INFO#*"VOLUME::"}
		OUTPUT=$(echo $INFO|cut -d \_ -f1)

		# Check our logic here to compare. Set volume accordingly.  Compare it
		# against maxVOLUME (as defined above) and then if it is violating that rule, lower the
		# volume.
		if [ "$OUTPUT" -gt "$maxVOLUME" ]
		then
	        	curl -s http://192.168.1.110:50101/data/rendererAction?data=VOLUME::$maxVOLUME &>/dev/null
		fi

		ctr=$(( ctr + 1 ))
	done
done
