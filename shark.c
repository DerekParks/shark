/* This souce code written my Michael Rolig (email: michael_rolig@alumni.macalester.edu)
 * This can be considered to be in the public domain
 *
 * Support for multiple RadioSHARK devices added on 4/10/2011 by Justin 
 * Yunke (e-mail: yunke@productivity.org).
 *
 * This code is still considered to be in the public domain
 *
 * To use multiple RadioSHARK cards, add a command line parameter with 
 * the number of RadioSHARK devices to "skip" past.  Since the RadioSHARK 
 * devices don't have a serial number, this is probably the easiest way 
 * to do it.
 */

#define SHARK_VERSION "1.0 4/17/2011"
#define DEBUG false		/* Set true for copious debugging output */
#define SHARK_VENDID 0x077d	/* Griffin's Vendor ID */
#define SHARK_DEVID 0x627a	/* The radioSHARK's Device ID */

#define READ_EP 0x5		/* libhid read command? */
#define WRITE_EP 0x5		/* libhid write command? */
#define SEND_PACKET_LENGTH 6	/* size of an instruction packet */

#include <stdio.h>
#include <string.h>
#include <unistd.h>
#include <hid.h>
#include <stdbool.h>
#include <usb.h>
void usage(int argc, const char** argv) {
	printf("Shark Version %s\n\n",SHARK_VERSION);
	printf("%s <command> <arg> [skip]\n\tchange state of radioSHARK\n\n", argv[0]);
	printf("commands:\n"
		" -fm <freqeuncy>    : set FM frequency, e.g. '-fm 91.5'\n"
		" -am <frequency>    : set AM frequency, e.g. '-am 730'\n"
		" -blue <intensity>  : turn on blue LED (0-127) '-blue 127'\n"
		" -bblue <freqency>  : turn on blue LED pulsing (0-127) '-bblue 64'\n"
		" -red <0/1>         : turn on/off red LED '-red 1'\n\n"
		"Optional argument [skip] is the number of USB devices to skip\nwhen using multiple RadioSHARKs.\n");
}

bool matcher_skip_fn(struct usb_dev_handle const* dev_h, void* custom, unsigned int len) {
  struct usb_device const* dev = usb_device((usb_dev_handle*)dev_h);
  unsigned int* skip = custom;

  if (*skip == 0) {
    return true;
  }

  if (dev->descriptor.idVendor == SHARK_VENDID && dev->descriptor.idProduct == SHARK_DEVID) {
    *skip = *skip - 1;
  }

  return false;
}

int main(int argc, const char** argv) {

	/* Declare variables used later */
	hid_return ret;
	HIDInterface* hid;
	unsigned int skip = 0;
	HIDInterfaceMatcher matcher = { SHARK_VENDID, SHARK_DEVID, *matcher_skip_fn, &skip, 0 };

	/* Build the instruction packet to send to the shark */
	unsigned char PACKET[SEND_PACKET_LENGTH] = { 0x00, 0x00, 0x00, 0x00, 0x00, 0x00 };
	unsigned short encodedFreq;
	float freq;
	unsigned short stereo;
	int intensity; 
        if (argc == 4) {
          skip = (unsigned int)atoi(argv[3]);
        }
	if (argc == 3 || argc == 4) {
		if (strcmp(argv[1], "-fm") == 0) {
			/* Tune to an FM frequency */
			PACKET[0] = 0xC0;
			encodedFreq = 0;
			freq = atof(argv[2]);
			encodedFreq  = ((freq * 1000) + 10700) / 12.5;
			encodedFreq += 3;
			PACKET[2] = (encodedFreq >> 8) & 0xFF;
			PACKET[3] = encodedFreq & 0xFF;
			if (DEBUG) {
				printf("band = fm\n");
				printf("freq = %.1f\n", freq);
				printf("encoded freq = 0x%x\n", (unsigned int)encodedFreq);
			}
		} else if (strcmp(argv[1], "-am") == 0) {
			/* Tune to an AM frequency */
			PACKET[0] = 0xC0;
			encodedFreq = 0;
			freq = (float)atoi(argv[2]);
			encodedFreq  = ((unsigned short)freq) + 450;
			PACKET[1] = 0x12;
			PACKET[2] = (encodedFreq >> 8) & 0xFF;
			PACKET[3] = encodedFreq & 0xFF;
			if (DEBUG) {
				printf("band = am\n");
				printf("freq = %d\n", (unsigned int)freq);
				printf("encoded freq = 0x%x\n", (unsigned int)encodedFreq);
			}
		} else if (strcmp(argv[1], "-blue") == 0) {
			/* Adjust the blue LED */
			intensity = atoi(argv[2]);
			PACKET[0] = 0xA0;
			PACKET[1] = (char)intensity;
		} else if (strcmp(argv[1], "-bblue") == 0) {
			/* Adjust the blue LED's pulsing rate */
			intensity = atoi(argv[2]);
			PACKET[0] = 0xA1;
			PACKET[1] = (char)intensity;
		} else if (strcmp(argv[1], "-red") == 0) {
			/* Toggle the red LED */
			intensity = atoi(argv[2]);
			if (intensity) PACKET[0] = 0xA9;
			else PACKET[0] = 0xA8;
			PACKET[1] = (char)intensity;
		} else {
			/* Bad command - display the program's usage instructions */
			usage(argc, argv);
			exit(1);
		}
	} else {
		usage(argc, argv);
		exit(1);
	}

	/* Turn libhid debugging on if requested.  See include/debug.h for possible values. */
	if (DEBUG) {
		hid_set_debug(HID_DEBUG_ALL);
		hid_set_debug_stream(stderr);
		hid_set_usb_debug(0);			/* passed directly to libusb */
	}

	/* Initialize the hid library */
	ret = hid_init();
	if (ret != HID_RET_SUCCESS) {
		fprintf(stderr, "hid_init failed with return code %d\n", ret);
		return 1;
	}

	/* Initialize the hid object */
	hid = hid_new_HIDInterface();
	if (hid == 0) {
		fprintf(stderr, "hid_new_HIDInterface() failed, out of memory?\n");
		return 1;
	}

	/* Open the shark */
	ret = hid_force_open(hid, 2, &matcher, 3);
	if (ret != HID_RET_SUCCESS) {
		fprintf(stderr, "hid_force_open failed with return code %d\n", ret);
		return 1;
	}

	/* Send the instruction packet constructed above to the Shark */
	ret = hid_interrupt_write(hid, WRITE_EP, (char*)PACKET, SEND_PACKET_LENGTH, 10000);
	if (ret != HID_RET_SUCCESS) fprintf(stderr, "hid_interrupt_write failed with return code %d\n", ret);

	/* Close the shark */
	ret = hid_close(hid);
	if (ret != HID_RET_SUCCESS) {
		fprintf(stderr, "hid_close failed with return code %d\n", ret);
		return 1;
	}

	/* Delete the hid object */
	hid_delete_HIDInterface(&hid);

	/* Clean up the hid library */
	ret = hid_cleanup();
	if (ret != HID_RET_SUCCESS) {
		fprintf(stderr, "hid_cleanup failed with return code %d\n", ret);
		return 1;
	}

	return 0;
}
